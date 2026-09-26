import hashlib
import hmac
import secrets


def new_secret(size=48):
    return secrets.token_urlsafe(size)


def fingerprint(env, value):
    """Return a database-local HMAC; raw agent and pairing secrets are never stored."""
    params = env['ir.config_parameter'].sudo()
    key = params.get_param('baseer_pos_print_bridge.hmac_key')
    if not key:
        key = new_secret()
        params.set_param('baseer_pos_print_bridge.hmac_key', key)
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def constant_time_equal(left, right):
    return bool(left and right and hmac.compare_digest(left, right))
