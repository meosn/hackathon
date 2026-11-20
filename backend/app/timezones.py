"""Fixed GMT offsets for the picker, with support for saved regional time zones."""
import re
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

GMT_OFFSETS = sorted({*range(-12 * 60, 14 * 60 + 1, 60), -570, -210, -150, 210, 270, 330, 345, 390, 525, 570, 630, 765, 825})


def gmt_name(minutes):
    sign = "+" if minutes >= 0 else "-"
    hours, remainder = divmod(abs(minutes), 60)
    return f"GMT{sign}{hours:02}:{remainder:02}"


def resolve_timezone(value):
    if value == "GMT":
        return timezone.utc
    if value.startswith("GMT"):
        match = re.fullmatch(r"GMT([+-])(\d{1,2})(?::([0-5]\d))?", value)
        if not match:
            raise ValueError("Choose a valid GMT offset")
        minutes = (int(match[2]) * 60 + int(match[3] or 0)) * (1 if match[1] == "+" else -1)
        if not -720 <= minutes <= 840:
            raise ValueError("GMT offset must be between GMT-12 and GMT+14")
        return timezone(timedelta(minutes=minutes), gmt_name(minutes))
    return ZoneInfo(value)


def timezone_name(value):
    try:
        zone = resolve_timezone(value)
    except (ValueError, KeyError):
        raise ValueError("Choose a valid time zone or GMT offset") from None
    return gmt_name(int(zone.utcoffset(None).total_seconds() / 60)) if value.startswith("GMT") else value
