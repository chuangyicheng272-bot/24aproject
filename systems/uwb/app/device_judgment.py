from datetime import datetime

from pydantic import BaseModel


BELT_OFFLINE_TIMEOUT_SECONDS = 10
MIN_DISTANCE_MM = 0
MAX_DISTANCE_MM = 4500


class DeviceAlert(BaseModel):
    code: str
    message: str


def battery_alerts(battery: int) -> list[DeviceAlert]:
    if battery < 20:
        return [DeviceAlert(code="battery_low", message="腰帶電量過低")]
    return []


def is_belt_online(last_seen: datetime, now: datetime) -> bool:
    return (now - last_seen).total_seconds() <= BELT_OFFLINE_TIMEOUT_SECONDS


def offline_alerts(last_seen: datetime, now: datetime) -> list[DeviceAlert]:
    if not is_belt_online(last_seen, now):
        return [DeviceAlert(code="belt_offline", message="腰帶裝置離線")]
    return []


def is_distance_valid(distance_mm: int | float) -> bool:
    return MIN_DISTANCE_MM <= distance_mm <= MAX_DISTANCE_MM
