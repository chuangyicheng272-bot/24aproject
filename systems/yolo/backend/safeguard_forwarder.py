from __future__ import annotations

import os
import queue
import threading
from collections import deque
from datetime import datetime
from typing import Any

import requests


BEHAVIOR_ALERTS = {
    "疑似跌倒": (
        "fall_detected",
        "偵測到人員跌倒，請立即前往查看",
        "emergency",
    ),
    "揮手求救": (
        "help_requested",
        "偵測到人員揮手求救，請立即前往查看",
        "emergency",
    ),
    "步伐不穩": (
        "unstable_posture",
        "偵測到人員步伐不穩，請前往確認",
        "attention",
    ),
    "奔跑": (
        "unsafe_running",
        "偵測到人員於施工區奔跑，請前往確認",
        "attention",
    ),
}
PPE_ALERTS = {"未配戴安全帽", "未穿戴安全背心"}


def _environment_flag(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def _event_timestamp(event: dict[str, Any]) -> str:
    wall_time = event.get("wall_time")
    try:
        return datetime.fromtimestamp(float(wall_time)).astimezone().isoformat(
            timespec="seconds"
        )
    except (TypeError, ValueError, OSError):
        return datetime.now().astimezone().isoformat(timespec="seconds")


def build_safeguard_camera_payload(
    event: dict[str, Any], worker: dict[str, Any]
) -> dict[str, Any]:
    alerts = {str(item) for item in event.get("alerts", [])}
    worker_id = str(event.get("worker_id") or worker.get("worker_id") or "未識別")
    track_id = event.get("track_id", worker.get("track_id"))
    confidence = worker.get("confidence")
    base_detection = {
        "person_id": worker_id,
        "track_id": track_id,
        "confidence": confidence,
        "event_id": event.get("event_id"),
    }
    detections: list[dict[str, Any]] = []

    ppe = worker.get("ppe") or {}
    ppe_detection = dict(base_detection)
    if "未配戴安全帽" in alerts:
        ppe_detection["helmet"] = False
    elif isinstance(ppe.get("helmet"), bool):
        ppe_detection["helmet"] = ppe["helmet"]
    if "未穿戴安全背心" in alerts:
        ppe_detection["vest"] = False
    elif isinstance(ppe.get("vest"), bool):
        ppe_detection["vest"] = ppe["vest"]
    if alerts & PPE_ALERTS:
        detections.append(ppe_detection)

    for alert_label, (alert_type, message, severity) in BEHAVIOR_ALERTS.items():
        if alert_label not in alerts:
            continue
        detections.append(
            {
                **base_detection,
                "danger": True,
                "alert_type": alert_type,
                "alert_message": message,
                "severity": severity,
                "behavior": worker.get("behavior") or {},
            }
        )

    unmapped_alerts = alerts - PPE_ALERTS - set(BEHAVIOR_ALERTS)
    for alert_label in sorted(unmapped_alerts):
        detections.append(
            {
                **base_detection,
                "danger": True,
                "alert_type": "yolo_danger",
                "alert_message": f"YOLO 偵測到危險事件：{alert_label}",
                "severity": "serious" if event.get("risk_level") == "danger" else "attention",
            }
        )

    return {
        "camera_id": str(event.get("camera_id") or worker.get("camera_id") or "CAM-01"),
        "location": str(event.get("zone") or worker.get("zone") or "未設定位置"),
        "status": "online",
        "timestamp": _event_timestamp(event),
        "detections": detections,
        "source": "yolo-mediapipe",
    }


def post_safeguard_camera_payload(payload: dict[str, Any]) -> dict[str, Any]:
    base_url = os.getenv("SAFEGUARD_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    url = f"{base_url}/api/iot/camera"
    headers = {}
    api_key = os.getenv("SAFEGUARD_IOT_API_KEY", os.getenv("IOT_API_KEY", "")).strip()
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        timeout = float(os.getenv("SAFEGUARD_FORWARD_TIMEOUT_SECONDS", "3"))
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        try:
            response_data = response.json()
        except ValueError:
            response_data = None
        if response.status_code >= 400:
            return {
                "status": "failed",
                "url": url,
                "http_status": response.status_code,
                "error": f"SafeGuard returned HTTP {response.status_code}",
                "response": response_data,
            }
        return {
            "status": "success",
            "url": url,
            "http_status": response.status_code,
            "response": response_data,
        }
    except (requests.RequestException, TypeError, ValueError) as exc:
        return {"status": "failed", "url": url, "http_status": None, "error": str(exc)}


class SafeGuardAlertForwarder:
    """Use one background worker so network latency never blocks YOLO frames."""

    def __init__(self, queue_size: int = 100):
        self._queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(
            maxsize=queue_size
        )
        self._history: deque[dict[str, Any]] = deque(maxlen=20)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def dispatch(
        self, event: dict[str, Any], worker: dict[str, Any]
    ) -> dict[str, Any]:
        if not _environment_flag("SAFEGUARD_FORWARD_ENABLED", default=True):
            return {"status": "disabled"}
        payload = build_safeguard_camera_payload(event, worker)
        if not payload["detections"]:
            return {"status": "skipped", "reason": "no alert detections"}
        self._ensure_worker()
        event_id = str(event.get("event_id") or "")
        try:
            self._queue.put_nowait((event_id, payload))
        except queue.Full:
            result = {"status": "failed", "error": "SafeGuard forwarding queue is full"}
            self._remember(event_id, result)
            return result
        return {"status": "queued", "event_id": event_id}

    def status(self) -> dict[str, Any]:
        endpoint = (
            os.getenv("SAFEGUARD_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
            + "/api/iot/camera"
        )
        with self._lock:
            history = list(self._history)
        return {
            "enabled": _environment_flag("SAFEGUARD_FORWARD_ENABLED", default=True),
            "endpoint": endpoint,
            "api_key_configured": bool(
                os.getenv("SAFEGUARD_IOT_API_KEY", os.getenv("IOT_API_KEY", "")).strip()
            ),
            "pending": self._queue.qsize(),
            "recent_deliveries": history,
        }

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run,
                name="safeguard-yolo-forwarder",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        while True:
            event_id, payload = self._queue.get()
            try:
                result = post_safeguard_camera_payload(payload)
                self._remember(event_id, result)
            finally:
                self._queue.task_done()

    def _remember(self, event_id: str, result: dict[str, Any]) -> None:
        item = {
            "event_id": event_id,
            **result,
            "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        with self._lock:
            self._history.appendleft(item)
