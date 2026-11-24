"""Pure input checks also exercised without a running Odoo server."""
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import UUID


def number(value, label, minimum=0, maximum=100000, integer=False):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a number.')
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(f'{label} must be a number.') from None
    if not math.isfinite(result) or result < minimum or result > maximum or (integer and result != int(result)):
        raise ValueError(f'{label} must be between {minimum} and {maximum}' + (' and a whole number.' if integer else '.'))
    return int(result) if integer else result


def uuid_value(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Invalid request reference. Reopen the reservation screen.') from None


def time_range(start, end, zone):
    try:
        tz = ZoneInfo(zone)
        a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if a.tzinfo or b.tzinfo:
            raise ValueError()
        for d in (a, b):
            localized = d.replace(tzinfo=tz)
            if localized.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != d:
                raise ValueError()
        a = a.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
        b = b.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise ValueError('Enter a valid party start and end time.') from None
    if b <= a or (b - a).total_seconds() > 86400:
        raise ValueError('Party end must follow its start, within 24 hours.')
    return a, b


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and a_end > b_start
