DEFAULT_POS_CUSTOMER_PRELOAD = 2000


def post_init_hook(env):
    """Adopt the owner-approved POS customer preload without overwriting a tuned value."""
    params = env['ir.config_parameter'].sudo()
    key = 'point_of_sale.limited_customer_count'
    current = params.get_param(key)
    if current in (False, None, '', '100'):
        params.set_param(key, str(DEFAULT_POS_CUSTOMER_PRELOAD))
