from datetime import UTC, datetime
from zoneinfo import ZoneInfo

MONTEVIDEO = ZoneInfo("America/Montevideo")
_API_FORMAT = "%Y-%m-%dT%H:%M:%S"


def parse_local(value: str) -> datetime:
    """ISO 8601 -> datetime con zona. Sin zona explícita se asume Montevideo."""
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=MONTEVIDEO) if dt.tzinfo is None else dt.astimezone(MONTEVIDEO)


def to_api_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime(_API_FORMAT)


def from_api_utc(value: str) -> datetime:
    return datetime.strptime(value, _API_FORMAT).replace(tzinfo=UTC).astimezone(MONTEVIDEO)


def local_iso(dt: datetime) -> str:
    return dt.astimezone(MONTEVIDEO).isoformat()
