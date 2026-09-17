from __future__ import annotations

import threading
import time
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from .env import load_env_file
    from .modules.camera import FramePacket, VideoInput, VideoInputConfig, encode_jpeg, source_kind
    from .modules.worker_manager import WorkerManager
except ImportError:  # Allows `python app.py` from the backend directory.
    from env import load_env_file
    from modules.camera import FramePacket, VideoInput, VideoInputConfig, encode_jpeg, source_kind
    from modules.worker_manager import WorkerManager

try:
    import cv2
except ImportError:  # pragma: no cover - handled at runtime for setup guidance
    cv2 = None


load_env_file()

DEFAULT_CAMERA_SOURCE = os.environ.get("CAMERA_SOURCE", "test_videos/001.mp4")
#DEFAULT_CAMERA_SOURCE = os.environ.get("CAMERA_SOURCE", "http://10.98.150.196:8080")
DEFAULT_CAMERA_WIDTH = int(os.environ.get("CAMERA_WIDTH", "960"))
DEFAULT_CAMERA_HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "540"))
DEFAULT_CAMERA_TARGET_FPS = float(os.environ.get("CAMERA_TARGET_FPS", "30.0"))
DEFAULT_INFERENCE_FPS = float(os.environ.get("INFERENCE_FPS", "30.0"))
DEFAULT_STREAM_JPEG_QUALITY = int(os.environ.get("STREAM_JPEG_QUALITY", "85"))
DEFAULT_CAMERA_AUTO_CONTRAST = os.environ.get("CAMERA_AUTO_CONTRAST", "false").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DEFAULT_CAMERA_DENOISE = os.environ.get("CAMERA_DENOISE", "false").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
DEFAULT_CAMERA_SHARPEN = os.environ.get("CAMERA_SHARPEN", "false").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

@dataclass
class PairingRange:
    points: list[dict[str, float]] = field(
        default_factory=lambda: [
            {"x": 0.08, "y": 0.08},
            {"x": 0.92, "y": 0.08},
            {"x": 0.92, "y": 0.92},
            {"x": 0.08, "y": 0.92},
        ]
    )
    source: str = "manual_polygon"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "points": [
                {"x": round(point["x"], 4), "y": round(point["y"], 4)}
                for point in self.points
            ],
        }


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


class SafetyRuntime:
    def __init__(self):
        self.camera_config = VideoInputConfig(
            source=DEFAULT_CAMERA_SOURCE,
            width=DEFAULT_CAMERA_WIDTH,
            height=DEFAULT_CAMERA_HEIGHT,
            target_fps=DEFAULT_CAMERA_TARGET_FPS,
            stale_frame_grabs=0,
            auto_contrast=DEFAULT_CAMERA_AUTO_CONTRAST,
            denoise=DEFAULT_CAMERA_DENOISE,
            sharpen=DEFAULT_CAMERA_SHARPEN,
        )
        self.camera = VideoInput(self.camera_config)
        self.pairing_range = PairingRange()
        self.async_stream = True
        self.inference_fps = max(0.2, DEFAULT_INFERENCE_FPS)
        self.stream_jpeg_quality = max(40, min(95, DEFAULT_STREAM_JPEG_QUALITY))
        self.overlay_mode = "worker"
        self.last_inference_request = 0.0
        self.inference_lock = threading.Lock()
        self.manager_lock = threading.Lock()
        self.result_lock = threading.Lock()
        self.latest_result: dict[str, Any] | None = None
        self.latest_workers: list[dict[str, Any]] = []
        self.worker_manager = WorkerManager(
            camera_id="CAM-01",
            zone="預設監控區",
            fps=self._analysis_fps(),
        )

    def configure_camera(self, payload: dict[str, Any]) -> dict[str, Any]:
        previous_camera = self.camera
        previous_camera.close()

        self.camera_config = VideoInputConfig(
            source=str(payload.get("source") or self.camera_config.source),
            width=int(payload.get("width", self.camera_config.width)),
            height=int(payload.get("height", self.camera_config.height)),
            preserve_aspect=parse_bool(payload.get("preserve_aspect"), self.camera_config.preserve_aspect),
            target_fps=float(payload.get("target_fps", self.camera_config.target_fps)),
            low_latency=parse_bool(payload.get("low_latency"), self.camera_config.low_latency),
            buffer_size=int(payload.get("buffer_size", self.camera_config.buffer_size)),
            stale_frame_grabs=int(payload.get("stale_frame_grabs", self.camera_config.stale_frame_grabs)),
            brightness=float(payload.get("brightness", self.camera_config.brightness)),
            contrast=float(payload.get("contrast", self.camera_config.contrast)),
            auto_contrast=parse_bool(payload.get("auto_contrast"), self.camera_config.auto_contrast),
            clahe_clip_limit=float(payload.get("clahe_clip_limit", self.camera_config.clahe_clip_limit)),
            clahe_grid_size=int(payload.get("clahe_grid_size", self.camera_config.clahe_grid_size)),
            sharpen=parse_bool(payload.get("sharpen"), self.camera_config.sharpen),
            sharpen_amount=float(payload.get("sharpen_amount", self.camera_config.sharpen_amount)),
            denoise=parse_bool(payload.get("denoise"), self.camera_config.denoise),
            denoise_strength=float(payload.get("denoise_strength", self.camera_config.denoise_strength)),
            loop_file=parse_bool(payload.get("loop_file"), self.camera_config.loop_file),
        )
        self.camera = VideoInput(self.camera_config)
        self._configure_models(payload)
        if payload.get("async_stream") is not None:
            self.async_stream = parse_bool(payload.get("async_stream"), self.async_stream)
        if payload.get("inference_fps") is not None:
            self.inference_fps = max(0.2, float(payload["inference_fps"]))
        if payload.get("stream_jpeg_quality") is not None:
            self.stream_jpeg_quality = max(40, min(95, int(payload["stream_jpeg_quality"])))
        self.worker_manager.fps = self._analysis_fps()
        with self.manager_lock:
            self.worker_manager.tracker.reset()
            self.worker_manager.workers.clear()
            self.worker_manager.pose_history.clear()
            self.worker_manager.cached_equipment.clear()
            self.worker_manager.process_wall_times.clear()
            self.worker_manager.last_ppe_timestamp = -1e9
        self._clear_latest_result()
        return self.camera_status()

    def _configure_models(self, payload: dict[str, Any]) -> None:
        yolo = self.worker_manager.yolo
        changed = False
        if payload.get("person_model"):
            yolo.person_model_path = Path(payload["person_model"])
            yolo.person_model = None
            changed = True
        if payload.get("equipment_model"):
            yolo.equipment_model_path = Path(payload["equipment_model"])
            yolo.equipment_model = None
            changed = True
        if payload.get("person_confidence") is not None:
            yolo.person_confidence = float(payload["person_confidence"])
        if payload.get("equipment_confidence") is not None:
            yolo.equipment_confidence = float(payload["equipment_confidence"])
        if payload.get("max_people") is not None:
            value = int(payload["max_people"])
            yolo.max_people = value if value > 0 else None
        if payload.get("yolo_image_size") is not None:
            yolo.inference_size = max(320, int(payload["yolo_image_size"]))
        if changed:
            yolo.last_error = None

    def _analysis_fps(self) -> float:
        return self.inference_fps if self.async_stream else self.camera_config.target_fps

    def camera_status(self) -> dict[str, Any]:
        with self.manager_lock:
            models = self.worker_manager.status()["models"]
        return {
            "source": self.camera_config.source,
            "active_source": self.camera.active_source,
            "source_kind": source_kind(self.camera_config.source),
            "width": self.camera_config.width,
            "height": self.camera_config.height,
            "preserve_aspect": self.camera_config.preserve_aspect,
            "target_fps": self.camera_config.target_fps,
            "low_latency": self.camera_config.low_latency,
            "buffer_size": self.camera_config.buffer_size,
            "stale_frame_grabs": self.camera_config.stale_frame_grabs,
            "async_stream": self.async_stream,
            "inference_fps": self.inference_fps,
            "stream_jpeg_quality": self.stream_jpeg_quality,
            "brightness": self.camera_config.brightness,
            "contrast": self.camera_config.contrast,
            "auto_contrast": self.camera_config.auto_contrast,
            "clahe_clip_limit": self.camera_config.clahe_clip_limit,
            "clahe_grid_size": self.camera_config.clahe_grid_size,
            "sharpen": self.camera_config.sharpen,
            "sharpen_amount": self.camera_config.sharpen_amount,
            "denoise": self.camera_config.denoise,
            "denoise_strength": self.camera_config.denoise_strength,
            "loop_file": self.camera_config.loop_file,
            "is_open": self.camera.is_open,
            "pairing_range": self.pairing_range.to_dict(),
            "overlay_mode": self.overlay_mode,
            "models": models,
        }

    def configure_overlay_mode(self, payload: dict[str, Any]) -> dict[str, Any]:
        mode = str(payload.get("mode") or "worker").strip().lower()
        allowed_modes = {"worker", "mediapipe", "ppe"}
        if mode not in allowed_modes:
            raise ValueError("Overlay mode must be worker, mediapipe, or ppe.")
        self.overlay_mode = mode
        return {"mode": self.overlay_mode}

    def configure_pairing_range(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_points = payload.get("points", [])
        points = []
        for point in raw_points:
            x = max(0.0, min(1.0, float(point["x"])))
            y = max(0.0, min(1.0, float(point["y"])))
            points.append({"x": x, "y": y})

        if len(points) < 3:
            raise ValueError("Pairing range needs at least 3 points.")

        self.pairing_range = PairingRange(points=points)
        return self.pairing_range.to_dict()

    def process_once(self) -> dict[str, Any]:
        packet = None
        while packet is None:
            packet = self.camera.read()

        return self._process_packet(packet)

    def stream(self):
        while True:
            try:
                packet = self.camera.read()
            except Exception as exc:
                self._remember_stream_error(exc)
                time.sleep(0.5)
                continue
            if packet is None:
                time.sleep(0.01)
                continue

            if self.async_stream:
                self._maybe_start_background_inference(packet)
                result = self._latest_result_snapshot()
            else:
                result = self._process_packet(packet)

            frame = draw_overlay(packet.frame, result, self.overlay_mode, packet.timestamp)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + encode_jpeg(frame, quality=self.stream_jpeg_quality)
                + b"\r\n"
            )

    def _remember_stream_error(self, exc: Exception) -> None:
        with self.result_lock:
            previous = self.latest_result or {}
            errors = list(previous.get("errors", []))
            message = str(exc)
            if not errors or errors[-1] != message:
                errors.append(message)
            self.latest_result = {
                **previous,
                "errors": errors[-5:],
                "summary": {
                    **previous.get("summary", {}),
                    "stream_error": message,
                    "wall_time": time.time(),
                },
            }

    def worker_status(self) -> dict[str, Any]:
        with self.manager_lock:
            status = self.worker_manager.status()
        with self.result_lock:
            if self.latest_result is not None:
                status["workers"] = self.latest_result.get("workers", status["workers"])
                status["events"] = self.latest_result.get("events", status["events"])
                status["last_frame"] = self.latest_result.get("summary", status["last_frame"])
                status["last_errors"] = self.latest_result.get("errors", status["last_errors"])
        return status

    def alert_status(self) -> dict[str, Any]:
        status = self.worker_status()
        return {
            "events": status["events"],
            "active_workers": [
                worker
                for worker in status["workers"]
                if worker["risk_level"] != "normal"
            ],
        }

    def _process_packet(self, packet: FramePacket) -> dict[str, Any]:
        with self.manager_lock:
            result = self.worker_manager.process_frame(
                packet.frame,
                packet.timestamp,
                self.pairing_range.to_dict(),
            )
        result["frame"] = self._frame_info(packet)
        with self.result_lock:
            self.latest_result = result
            self.latest_workers = result.get("workers", [])
        return result

    def _maybe_start_background_inference(self, packet: FramePacket) -> None:
        if self.latest_result is None and packet.frame_index < 8:
            return
        now = time.monotonic()
        interval = 1.0 / max(float(self.inference_fps), 0.2)
        if now - self.last_inference_request < interval:
            return
        if self.inference_lock.locked():
            return

        self.last_inference_request = now
        packet_copy = FramePacket(
            frame=packet.frame.copy(),
            frame_index=packet.frame_index,
            timestamp=packet.timestamp,
            source=packet.source,
            width=packet.width,
            height=packet.height,
        )
        thread = threading.Thread(
            target=self._background_inference,
            args=(packet_copy,),
            daemon=True,
        )
        thread.start()

    def _background_inference(self, packet: FramePacket) -> None:
        with self.inference_lock:
            self._process_packet(packet)

    def _latest_workers(self) -> list[dict[str, Any]]:
        with self.result_lock:
            return list(self.latest_workers)

    def _latest_result_snapshot(self) -> dict[str, Any]:
        with self.result_lock:
            if self.latest_result is None:
                return {"workers": [], "detections": {"people": [], "equipment": []}, "poses": []}
            return dict(self.latest_result)

    def _clear_latest_result(self) -> None:
        with self.result_lock:
            self.latest_result = None
            self.latest_workers = []
        self.last_inference_request = 0.0

    def _frame_info(self, packet: FramePacket) -> dict[str, Any]:
        return {
            "frame_index": packet.frame_index,
            "timestamp": packet.timestamp,
            "source": packet.source,
            "width": packet.width,
            "height": packet.height,
        }


POSE_CONNECTIONS = (
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 7),
    (0, 4),
    (4, 5),
    (5, 6),
    (6, 8),
    (9, 10),
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (11, 23),
    (12, 24),
    (23, 24),
    (23, 25),
    (25, 27),
    (24, 26),
    (26, 28),
    (27, 29),
    (29, 31),
    (28, 30),
    (30, 32),
)


def draw_overlay(
    frame,
    result: dict[str, Any] | None,
    mode: str = "worker",
    frame_timestamp: float | None = None,
):
    if cv2 is None:
        return frame

    output = frame.copy()
    result = result or {}
    if mode == "mediapipe":
        draw_pose_overlay(output, result.get("poses", []))
    elif mode == "ppe":
        draw_ppe_overlay(output, result.get("detections", {}).get("equipment", []))
    else:
        draw_worker_overlay(output, result.get("workers", []), frame_timestamp)
    draw_overlay_status(output, result, mode)
    return output


def draw_overlay_status(output, result: dict[str, Any], mode: str) -> None:
    detections = result.get("detections", {})
    counts = {
        "worker": len(result.get("workers", [])),
        "mediapipe": len(result.get("poses", [])),
        "ppe": len(detections.get("equipment", [])),
    }
    label = {
        "worker": f"Worker mode: {counts['worker']} worker(s)",
        "mediapipe": f"MediaPipe mode: {counts['mediapipe']} pose(s)",
        "ppe": f"PPE mode: {counts['ppe']} item(s)",
    }.get(mode, f"{mode}: 0")
    errors = result.get("errors", {})
    if isinstance(errors, dict) and errors:
        label += " | check errors"
    cv2.rectangle(output, (10, 10), (min(output.shape[1] - 10, 360), 42), (14, 22, 19), -1)
    cv2.putText(
        output,
        label,
        (18, 32),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def draw_worker_overlay(
    output,
    workers: list[dict[str, Any]],
    frame_timestamp: float | None = None,
) -> None:
    for worker in workers:
        x1, y1, x2, y2 = predicted_worker_box(worker, output.shape[:2], frame_timestamp)
        coordinate = worker.get("coordinate", {}).get("frame", {}).get("pixel", {})
        coord_x, coord_y = predicted_worker_coordinate(worker, x1, y1, x2, y2, frame_timestamp)
        risk = worker.get("risk_level", "normal")
        color = {
            "normal": (40, 190, 110),
            "warning": (0, 185, 255),
            "danger": (40, 40, 230),
        }.get(risk, (255, 255, 255))
        label = f"{worker.get('worker_id')} / T{worker.get('track_id')}"
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        cv2.circle(output, (coord_x, coord_y), 5, color, -1, cv2.LINE_AA)
        cv2.putText(
            output,
            f"({coord_x},{coord_y})",
            (coord_x + 8, min(output.shape[0] - 8, coord_y + 18)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            color,
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            output,
            label,
            (x1, max(18, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )


def predicted_worker_box(
    worker: dict[str, Any],
    frame_shape: tuple[int, int],
    frame_timestamp: float | None,
    max_prediction_seconds: float = 0.65,
) -> tuple[int, int, int, int]:
    height, width = frame_shape
    x1, y1, x2, y2 = [float(value) for value in worker.get("box", [0, 0, 0, 0])]
    dx, dy = predicted_worker_delta(worker, frame_timestamp, max_prediction_seconds)
    box_width = max(1.0, x2 - x1)
    box_height = max(1.0, y2 - y1)
    x1 += dx
    x2 += dx
    y1 += dy
    y2 += dy

    if x1 < 0:
        x2 -= x1
        x1 = 0.0
    if y1 < 0:
        y2 -= y1
        y1 = 0.0
    if x2 > width:
        x1 -= x2 - width
        x2 = float(width)
    if y2 > height:
        y1 -= y2 - height
        y2 = float(height)

    x1 = max(0.0, min(float(width - 1), x1))
    y1 = max(0.0, min(float(height - 1), y1))
    x2 = max(x1 + box_width * 0.4, min(float(width), x2))
    y2 = max(y1 + box_height * 0.4, min(float(height), y2))
    return int(x1), int(y1), int(x2), int(y2)


def predicted_worker_coordinate(
    worker: dict[str, Any],
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    frame_timestamp: float | None,
) -> tuple[int, int]:
    coordinate = worker.get("coordinate", {}).get("frame", {}).get("pixel", {})
    if "x" not in coordinate or "y" not in coordinate:
        return int((x1 + x2) / 2), int(y1 + (y2 - y1) * 0.55)
    base_x = float(coordinate["x"])
    base_y = float(coordinate["y"])
    dx, dy = predicted_worker_delta(worker, frame_timestamp)
    return int(base_x + dx), int(base_y + dy)


def predicted_worker_delta(
    worker: dict[str, Any],
    frame_timestamp: float | None,
    max_prediction_seconds: float = 0.65,
) -> tuple[float, float]:
    if frame_timestamp is None:
        return 0.0, 0.0
    last_seen = worker.get("last_seen")
    if last_seen is None:
        return 0.0, 0.0
    elapsed = max(0.0, min(max_prediction_seconds, frame_timestamp - float(last_seen)))
    velocity = worker.get("velocity", {})
    vx = float(velocity.get("x", 0.0))
    vy = float(velocity.get("y", 0.0))
    return vx * elapsed, vy * elapsed


def draw_pose_overlay(output, poses: list[dict[str, Any]]) -> None:
    height, width = output.shape[:2]
    for pose_index, pose in enumerate(poses):
        landmarks = pose.get("landmarks", [])
        points: list[tuple[int, int] | None] = []
        for landmark in landmarks:
            visibility = float(landmark.get("visibility", 1.0))
            if visibility < 0.25:
                points.append(None)
                continue
            x = int(float(landmark.get("x", 0.0)) * width)
            y = int(float(landmark.get("y", 0.0)) * height)
            points.append((x, y))

        for start, end in POSE_CONNECTIONS:
            if start >= len(points) or end >= len(points):
                continue
            if points[start] is None or points[end] is None:
                continue
            cv2.line(output, points[start], points[end], (255, 190, 40), 2, cv2.LINE_AA)

        for point in points:
            if point is not None:
                cv2.circle(output, point, 3, (40, 235, 255), -1, cv2.LINE_AA)

        box = pose.get("box")
        if box:
            x1, y1, x2, y2 = normalized_box_to_pixels(box, width, height)
            cv2.rectangle(output, (x1, y1), (x2, y2), (255, 190, 40), 2)
            cv2.putText(
                output,
                f"MediaPipe {pose_index + 1}",
                (x1, max(18, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 190, 40),
                2,
                cv2.LINE_AA,
            )


def draw_ppe_overlay(output, equipment: list[dict[str, Any]]) -> None:
    colors = {
        "helmet": (40, 210, 255),
        "vest": (60, 220, 110),
        "gloves": (220, 190, 80),
        "shoes": (170, 220, 80),
        "no_helmet": (40, 40, 230),
        "no_vest": (40, 40, 230),
        "no_gloves": (40, 40, 230),
        "no_shoes": (40, 40, 230),
    }
    for item in equipment:
        x1, y1, x2, y2 = [int(value) for value in item.get("box", [0, 0, 0, 0])]
        kind = item.get("kind", item.get("label", "ppe"))
        color = colors.get(kind, (255, 255, 255))
        label = f"{kind} {int(float(item.get('confidence', 0.0)) * 100)}%"
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            output,
            label,
            (x1, max(18, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            color,
            2,
            cv2.LINE_AA,
        )


def normalized_box_to_pixels(box: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    return (
        int(float(x1) * width),
        int(float(y1) * height),
        int(float(x2) * width),
        int(float(y2) * height),
    )
