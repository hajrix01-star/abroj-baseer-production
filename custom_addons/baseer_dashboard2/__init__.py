from . import models


def post_init_hook(env):
    env['baseer.dashboard2.settings']._seed_documented_defaults()
    env['baseer.dashboard2.settings']._seed_food_purchase_accounts()
