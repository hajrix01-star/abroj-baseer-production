from odoo import fields, models


class ReportPosOrder(models.Model):
    _inherit = 'report.pos.order'

    baseer_root_pos_categ_id = fields.Many2one(
        'pos.category', string='Main POS Category', readonly=True,
        help='Top-level ancestor of the native POS category, using the current category hierarchy.')

    def _select(self):
        # Keep Odoo's original category selection and every original measure.
        return super()._select() + ', baseer_category_roots.root_id AS baseer_root_pos_categ_id'

    def _from(self):
        # A category has only one parent: this map cannot multiply report rows.
        # Categories without a reachable root stay unclassified via LEFT JOIN.
        return super()._from() + """
            LEFT JOIN (
                WITH RECURSIVE roots AS (
                    SELECT id, id AS root_id FROM pos_category WHERE parent_id IS NULL
                    UNION ALL
                    SELECT child.id, roots.root_id
                    FROM pos_category child JOIN roots ON child.parent_id = roots.id
                )
                SELECT id, root_id FROM roots
            ) baseer_category_roots ON baseer_category_roots.id = fpc.id
        """
