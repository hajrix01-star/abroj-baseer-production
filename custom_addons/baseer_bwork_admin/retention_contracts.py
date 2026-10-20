"""Pure scheduling and exact integer presentation. All instants are UTC naive."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_SOURCE_ROWS = 100000
MAX_VICTIMS = 1000
BATCH_SIZE = 100
PREVIEW_SECONDS = 300
MAX_POLICIES = 10


def size_label(size):
    if type(size) is not int or size < 0:
        raise ValueError('invalid_byte_count')
    for divisor, suffix in ((1073741824, 'GiB'), (1048576, 'MiB'), (1024, 'KiB')):
        if size >= divisor:
            value = (size * 100 + divisor // 2) // divisor
            return '%d.%02d %s' % (value // 100, value % 100, suffix)
    return '%d B' % size


def zone(value):
    try:
        if type(value) is not str or not 1 <= len(value) <= 80:
            raise ValueError()
        return ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError('invalid_timezone') from None


def local_slot(day, hour, minute, tz):
    if hour not in ['%02d' % i for i in range(24)] or minute not in ['%02d' % i for i in range(60)]:
        raise ValueError('invalid_schedule')
    day = date.fromisoformat(str(day))
    local = datetime.combine(day, time(int(hour), int(minute)))
    timezone_local = zone(tz)
    # Earliest UTC occurrence in an overlap; first valid minute after a gap.
    for _ in range(181):
        choices = []
        for fold in (0, 1):
            utc = local.replace(tzinfo=timezone_local, fold=fold).astimezone(timezone.utc)
            if utc.astimezone(timezone_local).replace(tzinfo=None) == local:
                choices.append(utc.replace(tzinfo=None))
        if choices:
            return min(choices)
        local += timedelta(minutes=1)
    raise ValueError('invalid_local_time')


def cutoff(mode, before_date, days, tz, now):
    if mode == 'before_date':
        day = date.fromisoformat(str(before_date))
    elif mode == 'older_than_days' and type(days) is int and 1 <= days <= 36500:
        day = now.replace(tzinfo=timezone.utc).astimezone(zone(tz)).date() - timedelta(days=days)
    else:
        raise ValueError('invalid_cutoff')
    result = local_slot(day, '00', '00', tz)
    if result > now:
        raise ValueError('future_cutoff')
    return result


def next_slot(now, hour, minute, tz):
    day = now.replace(tzinfo=timezone.utc).astimezone(zone(tz)).date()
    today = local_slot(day, hour, minute, tz)
    return today if today > now else local_slot(day + timedelta(days=1), hour, minute, tz)
