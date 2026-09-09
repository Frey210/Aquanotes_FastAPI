from datetime import datetime, timezone


def utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def apply_scheduled_deactivation(device, now: datetime | None = None) -> bool:
    scheduled = device.deactivation_scheduled_at
    if scheduled and utc_naive(scheduled) <= (now or datetime.utcnow()) and device.status != "inactive":
        device.status = "inactive"
        return True
    return False


def operational_mode(device) -> str:
    if device.deactivation_scheduled_at and utc_naive(device.deactivation_scheduled_at) <= datetime.utcnow():
        return "inactive"
    return device.status if device.status in {"maintenance", "inactive"} else "active"
