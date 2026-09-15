def post_init_hook(env):
    """Adopt the reviewed live root, or create it only when absent.

    Applicability stays unavailable during the mapping wave.  A mandatory
    vendor-bill rule before every company has an approved map would stop
    ordinary invoice posting on installation.
    """
    plan_model = env['account.analytic.plan'].sudo()
    imd_model = env['ir.model.data'].sudo()
    external = imd_model.search([
        ('module', '=', 'baseer_native_spend'),
        ('name', '=', 'spend_plan'),
        ('model', '=', 'account.analytic.plan'),
    ], limit=1)
    plan = plan_model.browse(external.res_id).exists() if external else plan_model.browse()
    # A previous development build may have left the XML id pointing at a
    # child plan.  Never adopt that record as the root: locate the reviewed
    # root instead and repair the reference below.
    if plan and (plan.parent_id or plan.name != 'تصنيف الإنفاق'):
        plan = plan_model.browse()
    if not plan:
        plan = plan_model.search([
            ('parent_id', '=', False),
            ('name', '=', 'تصنيف الإنفاق'),
        ], order='id', limit=1)
    if not plan:
        plan = plan_model.create({
            'name': 'تصنيف الإنفاق',
            'description': 'Native analytical dimension for vendor purchase and expense classification.',
            'default_applicability': 'unavailable',
            'sequence': 20,
        })
    if external:
        external.write({'res_id': plan.id})
    else:
        imd_model.create({
            'module': 'baseer_native_spend',
            'name': 'spend_plan',
            'model': 'account.analytic.plan',
            'res_id': plan.id,
            'noupdate': True,
        })
