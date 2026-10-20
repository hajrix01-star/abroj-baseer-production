"""Explicit legacy wire/data identities; never a second model or authority.

Remove a wire alias only after the distributed old client is retired. Opaque
UUIDs/digests/account keys and historical procurement provenance are not labels.
"""

LEGACY_SOURCE_CHANNEL = 'bchat'
LEGACY_ROUTE_PREFIX = '/bchat/'
CANONICAL_ROUTE_PREFIX = '/bwork/'
LEGACY_UPLOAD_SCHEME = 'BChatUpload '
CANONICAL_UPLOAD_SCHEME = 'BWorkUpload '
EXTERNAL_ADDON_DEPENDENCIES = ('baseer_bchat_notifications', 'baseer_bchat_documents')
_HEADER_ALIASES = {
    'X-BWork-Content-Revision': 'X-BChat-Content-Revision',
    'X-BWork-Avatar-Version': 'X-BChat-Avatar-Version',
}


def routes(canonical):
    """Publish one controller at two paths with identical auth/CSRF/limits."""
    if not isinstance(canonical, str) or not canonical.startswith(CANONICAL_ROUTE_PREFIX):
        raise ValueError('A canonical BWork route is required.')
    return [canonical, LEGACY_ROUTE_PREFIX + canonical[len(CANONICAL_ROUTE_PREFIX):]]


def response_header(name, value):
    if name not in _HEADER_ALIASES:
        raise ValueError('Unknown compatibility header.')
    return [(name, str(value)), (_HEADER_ALIASES[name], str(value))]


def validate_headers(headers):
    """Reject ambiguous new/old claims; neither header grants authority."""
    for canonical, legacy in _HEADER_ALIASES.items():
        current, old = headers.get(canonical), headers.get(legacy)
        if current is not None and old is not None and current != old:
            raise ValueError('Conflicting compatibility headers.')


def upload_token(authorization):
    for prefix in (CANONICAL_UPLOAD_SCHEME, LEGACY_UPLOAD_SCHEME):
        if isinstance(authorization, str) and authorization.startswith(prefix):
            return authorization[len(prefix):]
    raise ValueError('Invalid upload authorization scheme.')


def wire_payload(payload, request_path):
    """Only generated URL fields adapt; never rewrite message/user content."""
    if not isinstance(request_path, str) or not request_path.startswith(LEGACY_ROUTE_PREFIX):
        return payload
    def adapt(value):
        if isinstance(value, list):
            return [adapt(item) for item in value]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if (key == 'image_url' and isinstance(item, str)
                        and item.startswith(CANONICAL_ROUTE_PREFIX)):
                    item = LEGACY_ROUTE_PREFIX + item[len(CANONICAL_ROUTE_PREFIX):]
                result[key] = adapt(item)
            return result
        return value
    return adapt(payload)
