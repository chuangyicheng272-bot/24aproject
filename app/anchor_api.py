from datetime import datetime, timezone
from typing import Literal

import requests
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .device_judgment import MAX_DISTANCE_MM, MIN_DISTANCE_MM, is_distance_valid


router = APIRouter(prefix="/api/anchor", tags=["anchor"])

FLASK_RANGE_URL = "http://192.168.2.171:5000/api/uwb/range"
FORWARD_TIMEOUT_SECONDS = 3

latest_anchor_reports: dict[str, dict] = {}
anchor_report_history: list[dict] = []
latest_belt_ranges: dict[str, dict] = {}

class BeltRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distance_mm: int | float

    @field_validator("distance_mm", mode="before")
    @classmethod
    def validate_distance(cls, value: object) -> int | float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("distance_mm must be an integer or number")
        if not is_distance_valid(value):
            raise ValueError(
                f"distance_invalid: distance_mm must be between "
                f"{MIN_DISTANCE_MM} and {MAX_DISTANCE_MM}"
            )
        return value


class AnchorRangesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence_id: int = Field(..., strict=True, ge=0)
    anchor_id: Literal["Anchor1", "Anchor2", "Anchor3", "Anchor4"]
    timestamp: int = Field(..., strict=True, ge=0)
    detected_belts: dict[str, BeltRange]

    @field_validator("detected_belts")
    @classmethod
    def validate_belt_ids(cls, value: dict[str, BeltRange]) -> dict[str, BeltRange]:
        if any(not belt_id.strip() for belt_id in value):
            raise ValueError("belt_id must be a non-empty string")
        return value


def post_to_flask(body: dict) -> tuple[int | None, str | None]:
    try:
        response = requests.post(
            FLASK_RANGE_URL,
            json=body,
            timeout=FORWARD_TIMEOUT_SECONDS,
        )
        return response.status_code, None
    except requests.RequestException as exc:
        return None, str(exc)


@router.post("/ranges")
def receive_anchor_ranges(payload: AnchorRangesPayload) -> dict:
    server_received_at = datetime.now(timezone.utc).isoformat()
    report = {
        **payload.model_dump(),
        "server_received_at": server_received_at,
    }
    latest_anchor_reports[f"{payload.anchor_id}:{payload.sequence_id}"] = report
    anchor_report_history.append(report)

    forwards = []
    for belt_id, belt_range in payload.detected_belts.items():
        range_payload = {
            "belt_id": belt_id,
            "sequence_id": payload.sequence_id,
            "anchor_id": payload.anchor_id,
            "timestamp": payload.timestamp,
            "distance_mm": belt_range.distance_mm,
        }
        latest_belt_ranges[
            f"{belt_id}:{payload.sequence_id}:{payload.anchor_id}"
        ] = {**range_payload, "server_received_at": server_received_at}
        status_code, error = post_to_flask(range_payload)
        forwards.append(
            {
                "url": FLASK_RANGE_URL,
                "payload": range_payload,
                "status_code": status_code,
                "error": error,
            }
        )

    has_error = any(item["error"] for item in forwards)
    return {
        "status": "forward_error" if has_error else "success",
        "data": report,
        "flask_forwards": forwards,
    }
