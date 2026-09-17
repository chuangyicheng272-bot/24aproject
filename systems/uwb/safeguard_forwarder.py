import logging
import os
from datetime import datetime

import requests


logger = logging.getLogger(__name__)


def _environment_flag(name, default=True):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _risk_for_assessment(assessment):
    if not assessment.get("zone"):
        return "低風險"
    if str(assessment.get("zone_risk", "")).lower() == "high":
        return "中高風險"
    return "注意"


def build_safeguard_payload(belt, position, assessment, timestamp=None):
    """Convert a calculated UWB position to SafeGuard's IoT payload."""
    zone = assessment.get("zone") or None
    in_danger_zone = zone is not None
    zone_name = str(zone.get("name") if zone else "安全區域")
    risk = _risk_for_assessment(assessment)
    occurred_at = timestamp or datetime.now().astimezone().isoformat(timespec="seconds")

    payload = {
        "device_id": str(belt["belt_id"]),
        "name": str(belt.get("device_name") or belt["belt_id"]),
        "x": float(position["x"]),
        "y": float(position["y"]),
        "z": float(position.get("z", 0)),
        "battery": int(belt.get("battery", 100)),
        "status": "online" if belt.get("online", True) else "offline",
        "area": zone_name,
        "risk": risk,
        "inside_safe_zone": not in_danger_zone,
        "boundary_status": "danger" if in_danger_zone else "inside",
        "timestamp": occurred_at,
        "position_unit": "mm",
        "source": "uwb-positioning",
    }
    if in_danger_zone:
        payload.update(
            {
                "danger": True,
                "alert_type": "geofence_intrusion",
                "alert_message": f"{belt['belt_id']} 進入{zone_name}，請立即前往查看",
                "severity": "serious" if risk == "中高風險" else "attention",
            }
        )
    return payload


def forward_uwb_position(belt, position, assessment, timestamp=None):
    """Post one calculated position to SafeGuard without interrupting UWB."""
    base_url = os.getenv("SAFEGUARD_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    url = f"{base_url}/api/iot/uwb"
    if not _environment_flag("SAFEGUARD_FORWARD_ENABLED", default=True):
        return {"status": "disabled", "url": url}

    payload = build_safeguard_payload(belt, position, assessment, timestamp)
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
            error = f"SafeGuard returned HTTP {response.status_code}"
            logger.error("UWB position forwarding failed: %s", error)
            return {
                "status": "failed",
                "url": url,
                "http_status": response.status_code,
                "error": error,
                "response": response_data,
            }
        return {
            "status": "success",
            "url": url,
            "http_status": response.status_code,
            "response": response_data,
        }
    except (requests.RequestException, TypeError, ValueError) as exc:
        logger.error("UWB position forwarding failed: %s", exc)
        return {"status": "failed", "url": url, "http_status": None, "error": str(exc)}
