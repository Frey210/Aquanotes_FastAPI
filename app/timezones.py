from datetime import datetime, timezone
from zoneinfo import ZoneInfo


WIB_PROVINCES = {
    "ACEH",
    "SUMATERA UTARA",
    "SUMATERA BARAT",
    "RIAU",
    "KEPULAUAN RIAU",
    "JAMBI",
    "BENGKULU",
    "SUMATERA SELATAN",
    "KEPULAUAN BANGKA BELITUNG",
    "LAMPUNG",
    "BANTEN",
    "DKI JAKARTA",
    "JAWA BARAT",
    "JAWA TENGAH",
    "DI YOGYAKARTA",
    "DAERAH ISTIMEWA YOGYAKARTA",
    "JAWA TIMUR",
    "KALIMANTAN BARAT",
    "KALIMANTAN TENGAH",
}


def tambak_timezone(tambak) -> ZoneInfo:
    if not tambak or (tambak.country or "").strip().upper() != "INDONESIA":
        return ZoneInfo("UTC")
    province = (tambak.province or "").strip().upper()
    if province in WIB_PROVINCES:
        return ZoneInfo("Asia/Jakarta")
    if "MALUKU" in province or "PAPUA" in province:
        return ZoneInfo("Asia/Jayapura")
    return ZoneInfo("Asia/Makassar")


def utc_to_tambak_time(value: datetime | None, tambak) -> datetime | None:
    if value is None:
        return None
    utc_value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return utc_value.astimezone(tambak_timezone(tambak)).replace(tzinfo=None)


def tambak_time_to_utc(value: datetime, tambak) -> datetime:
    return value.replace(tzinfo=tambak_timezone(tambak)).astimezone(timezone.utc).replace(tzinfo=None)
