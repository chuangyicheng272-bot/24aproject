import logging
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import FLASK_BELT_STATUS_URL, FORWARD_TIMEOUT_SECONDS
from .device_judgment import battery_alerts, is_belt_online, offline_alerts


router = APIRouter(prefix="/api/belt", tags=["belt"])
logger = logging.getLogger(__name__)
belt_statuses: dict[str, dict] = {}


def post_to_flask(body: dict) -> tuple[int | None, str | None]:
    try:
        response = requests.post(
            FLASK_BELT_STATUS_URL,
            json=body,
            timeout=FORWARD_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            logger.error(
                "Flask belt status forwarding returned HTTP %s", response.status_code
            )
            return response.status_code, f"Flask returned HTTP {response.status_code}"
        return response.status_code, None
    except requests.RequestException as exc:
        logger.error("Flask belt status forwarding failed: %s", exc)
        return None, str(exc)


class BeltStatusPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    belt_id: str = Field(..., strict=True)
    timestamp: int = Field(..., strict=True, ge=0)
    battery: int = Field(..., strict=True, ge=0, le=100)
    charging: bool = Field(..., strict=True)

    @field_validator("belt_id")
    @classmethod
    def validate_belt_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("belt_id must be a non-empty string")
        return value


@router.post("/status")
def receive_belt_status(payload: BeltStatusPayload) -> dict:
    received_at = datetime.now(timezone.utc)
    status = {
        "belt_id": payload.belt_id,
        "battery": payload.battery,
        "charging": payload.charging,
        "device_timestamp": payload.timestamp,
        "last_seen": received_at,
        "server_received_at": received_at,
    }
    belt_statuses[payload.belt_id] = status
    public_status = _public_status(status, received_at)
    forward_payload = {
        "belt_id": payload.belt_id,
        "timestamp": payload.timestamp,
        "battery": payload.battery,
        "charging": payload.charging,
        "online": public_status["online"],
    }
    status_code, error = post_to_flask(forward_payload)
    return {
        "status": "forward_error" if error else "success",
        "forward_status": "forward_error" if error else "success",
        "forward_error": "Flask connection failed" if error else None,
        "data": public_status,
        "flask_forward": {
            "url": FLASK_BELT_STATUS_URL,
            "payload": forward_payload,
            "status_code": status_code,
            "error": error,
        },
    }


@router.get("/{belt_id}/status")
def get_belt_status(belt_id: str) -> dict:
    status = belt_statuses.get(belt_id)
    if status is None:
        raise HTTPException(status_code=404, detail="belt status not found")
    return _public_status(status, datetime.now(timezone.utc))


def _public_status(status: dict, now: datetime) -> dict:
    alerts = battery_alerts(status["battery"]) + offline_alerts(
        status["last_seen"], now
    )
    return {
        "belt_id": status["belt_id"],
        "battery": status["battery"],
        "charging": status["charging"],
        "online": is_belt_online(status["last_seen"], now),
        "last_seen": status["last_seen"].isoformat(),
        "alerts": [alert.model_dump() for alert in alerts],
    }
