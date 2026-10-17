"""Provider error interpretation without Odoo, credentials, or message content."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math


_MAX_RETRY_SECONDS = 86400
_FCM_ERROR_TYPE = 'type.googleapis.com/google.firebase.fcm.v1.FcmError'


def retry_after_seconds(value, now):
    if not isinstance(value, str) or len(value) > 128:
        return None
    try:
        stripped = value.strip()
        if stripped.isascii() and stripped.isdecimal():
            delay = int(stripped)
        else:
            stamp = parsedate_to_datetime(stripped)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
            delay = math.ceil((stamp - current).total_seconds())
        return min(_MAX_RETRY_SECONDS, max(0, delay))
    except (TypeError, ValueError, OverflowError):
        return None


def classify_fcm_failure(status_code, payload, retry_after=None, now=None):
    """Only a typed FCM UNREGISTERED detail invalidates a device token."""
    error = payload.get('error') if isinstance(payload, dict) else None
    details = error.get('details') if isinstance(error, dict) else None
    fcm_code = None
    if isinstance(details, list):
        for detail in details[:32]:
            if isinstance(detail, dict) and detail.get('@type') == _FCM_ERROR_TYPE:
                code = detail.get('errorCode')
                if isinstance(code, str):
                    fcm_code = code
                    break
    if fcm_code == 'UNREGISTERED':
        return {'code': 'unregistered', 'retry': False, 'invalid_token': True,
                'retry_after': None}
    if status_code in (401, 403, 404):
        return {'code': 'configuration', 'retry': False, 'invalid_token': False,
                'retry_after': None}
    if status_code == 400:
        return {'code': 'invalid_payload', 'retry': False, 'invalid_token': False,
                'retry_after': None}
    return {'code': 'quota' if status_code == 429 else 'transport',
            'retry': True, 'invalid_token': False,
            'retry_after': retry_after_seconds(retry_after, now or datetime.now(timezone.utc))}


def retry_delay_seconds(attempt, provider_delay=None, jitter=0.0):
    """Positive bounded backoff, never earlier than a valid provider hint."""
    base = min(3600, 60 * (2 ** min(6, max(0, attempt - 1))))
    if isinstance(provider_delay, int) and not isinstance(provider_delay, bool):
        base = max(base, min(_MAX_RETRY_SECONDS, max(0, provider_delay)))
    fraction = min(0.2, max(0.0, float(jitter)))
    return min(_MAX_RETRY_SECONDS, math.ceil(base * (1.0 + fraction)))
