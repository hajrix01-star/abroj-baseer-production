from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for key, rate in (("keeta", 18), ("hunger", 22), ("jahez", 20)):
        channel = env.ref("baseer_dashboard2.channel_" + key, raise_if_not_found=False)
        if channel and not channel.commission_rate:
            channel.commission_rate = rate
