from . import models
from . import controllers


def post_init_hook(env):
    # Fresh core scope only: no roles, readiness, policies, cron or business rows.
    from .tools.canonical_pre_upgrade import attest_fresh
    attest_fresh(env.cr)
