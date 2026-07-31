from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .device_judgment import battery_alerts, is_belt_online, offline_alerts


router = APIRouter(prefix="/api/belt", tags=["belt"])
belt_statuses: dict[str, dict] = {}


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
    return {
        "status": "success",
        "data": _public_status(status, received_at),
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
