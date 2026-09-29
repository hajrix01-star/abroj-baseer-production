from odoo import api, fields, models


DEFAULT_CATEGORIES = (
    ("prep", "تجهيز وتحضير", "Preparation"),
    ("structure", "بناء وأعمال مدنية", "Civil works"),
    ("finishing", "تشطيبات", "Finishing"),
    ("flooring", "أرضيات", "Flooring"),
    ("walls", "جدران", "Walls"),
    ("ceilings", "أسقف", "Ceilings"),
    ("paint", "دهانات", "Paint"),
    ("electrical", "كهرباء", "Electrical"),
    ("lighting", "إنارة", "Lighting"),
    ("plumbing", "سباكة", "Plumbing"),
    ("hvac", "تكييف", "HVAC"),
    ("glass", "زجاج", "Glass"),
    ("carpentry", "نجارة", "Carpentry"),
    ("marble", "رخام وحجر", "Marble & stone"),
    ("counters", "بار وكاونترات", "Bars & counters"),
    ("security", "أنظمة مراقبة", "Security systems"),
    ("furniture", "أثاث", "Furniture"),
    ("decor", "ديكور", "Decor"),
    ("signage", "لوحات وشعارات", "Signage"),
    ("external", "أعمال خارجية", "External works"),
    ("other", "أخرى", "Other"),
)

DEFAULT_STAGE_TEMPLATES = (
    ("site_preparation", "تجهيز الموقع", "Site preparation", 2),
    ("civil_works", "أعمال البناء", "Civil works", 5),
    ("plumbing", "السباكة", "Plumbing", 3),
    ("electrical", "الكهرباء", "Electrical", 4),
    ("hvac", "التكييف", "HVAC", 4),
    ("ceilings_gypsum", "الأسقف والجبس", "Ceilings & gypsum", 4),
    ("flooring", "الأرضيات", "Flooring", 4),
    ("walls_paint", "الجدران والدهان", "Walls & paint", 4),
    ("carpentry_counters", "النجارة والبار", "Carpentry & counters", 4),
    ("glass_facades", "الزجاج والواجهات", "Glass & facades", 3),
    ("lighting_systems", "الإنارة والأنظمة", "Lighting & systems", 3),
    ("furniture_decor", "الأثاث والديكور", "Furniture & decor", 3),
    ("cleaning_handover", "تنظيف وتسليم", "Cleaning & handover", 2),
)

DEFAULT_STAGE_SELECTION = [(key, name) for key, name, _name_en, _duration in DEFAULT_STAGE_TEMPLATES]
DEFAULT_STAGE_MAP = {key: (name, duration) for key, name, _name_en, duration in DEFAULT_STAGE_TEMPLATES}

# Prices intentionally remain at Odoo's zero defaults.
DEFAULT_MATERIALS = (
    ("cement", "أسمنت", "Cement", "structure"), ("sand", "رمل بناء", "Building sand", "structure"),
    ("gravel", "بحص", "Gravel", "structure"), ("concrete_block", "بلوك خرساني", "Concrete block", "structure"),
    ("red_brick", "طابوق أحمر", "Red brick", "structure"), ("ready_mix_concrete", "خرسانة جاهزة", "Ready-mix concrete", "structure"),
    ("rebar", "حديد تسليح", "Reinforcement steel", "structure"), ("gypsum_board", "جبس بورد", "Gypsum board", "ceilings"),
    ("gypsum_compound", "معجون جبس", "Gypsum compound", "ceilings"), ("ceramic_tile", "سيراميك", "Ceramic tile", "flooring"),
    ("porcelain_tile", "بورسلان", "Porcelain tile", "flooring"), ("tile_adhesive", "غراء بلاط", "Tile adhesive", "flooring"),
    ("tile_grout", "روبة بلاط", "Tile grout", "flooring"), ("marble", "رخام", "Marble", "marble"),
    ("granite", "جرانيت", "Granite", "marble"), ("wall_paint", "دهان جدران", "Wall paint", "paint"),
    ("primer", "برايمر", "Primer", "paint"), ("electrical_cable", "كيابل كهرباء", "Electrical cable", "electrical"),
    ("electrical_conduit", "مواسير كهرباء", "Electrical conduit", "electrical"), ("switch_socket", "مفاتيح وأفياش", "Switches & sockets", "electrical"),
    ("led_panel", "لوح إنارة LED", "LED panel", "lighting"), ("spotlight", "سبوت لايت", "Spotlight", "lighting"),
    ("water_pipe", "مواسير مياه", "Water pipes", "plumbing"), ("drain_pipe", "مواسير صرف", "Drain pipes", "plumbing"),
    ("sanitary_ware", "أدوات صحية", "Sanitary ware", "plumbing"), ("air_conditioner", "مكيف", "Air conditioner", "hvac"),
    ("air_duct", "دكت تكييف", "Air duct", "hvac"), ("aluminum_profile", "ألمنيوم", "Aluminium profile", "glass"),
    ("clear_glass", "زجاج شفاف", "Clear glass", "glass"), ("wood_board", "ألواح خشب", "Wood boards", "carpentry"),
    ("door", "باب", "Door", "carpentry"), ("cctv_camera", "كاميرا مراقبة", "CCTV camera", "security"),
    ("cafe_chair", "كرسي مقهى", "Cafe chair", "furniture"), ("table", "طاولة", "Table", "furniture"),
    ("artificial_plant", "نباتات صناعية", "Artificial plants", "decor"), ("signboard", "لوحة محل", "Shop signboard", "signage"),
)


class AbrojCostCategory(models.Model):
    _inherit = "abroj.cost.category"
    seed_key = fields.Char(index=True, copy=False)
    name_en = fields.Char(string="الاسم بالإنجليزية")


class AbrojCostProgressStage(models.Model):
    _inherit = "abroj.cost.progress.stage"
    stage_template_key = fields.Selection(DEFAULT_STAGE_SELECTION, string="مرحلة افتراضية")

    @api.onchange("stage_template_key")
    def _onchange_stage_template_key(self):
        for stage in self:
            if stage.stage_template_key:
                stage.name, stage.planned_duration_days = DEFAULT_STAGE_MAP[stage.stage_template_key]


class AbrojCostDefaults(models.AbstractModel):
    _name = "abroj.cost.defaults"
    _description = "ABROJ Costing Defaults"

    @api.model
    def ensure_for_company(self, company):
        company = company.sudo()
        Category = self.env["abroj.cost.category"].sudo()
        Material = self.env["abroj.cost.material"].sudo()
        categories = {}
        for sequence, (key, name, name_en) in enumerate(DEFAULT_CATEGORIES, start=1):
            category = Category.search([("company_id", "=", company.id), ("seed_key", "=", key)], limit=1)
            if not category:
                category = Category.search([("company_id", "=", company.id), ("name", "=", name)], limit=1)
            if category:
                category.write({"name_en": name_en, "seed_key": key, "sequence": sequence})
            else:
                category = Category.create({"name": name, "name_en": name_en, "seed_key": key, "sequence": sequence, "company_id": company.id})
            categories[key] = category
        material_defaults = Material.default_get(["uom_type", "default_pricing_method"])
        for code, name, name_en, category_key in DEFAULT_MATERIALS:
            if not Material.search_count([("company_id", "=", company.id), ("code", "=", code)]):
                vals = dict(material_defaults)
                vals.update({
                    "code": code,
                    "name": name,
                    "name_en": name_en,
                    "category_id": categories[category_key].id,
                    "company_id": company.id,
                    "material_unit_cost": 0.0,
                    "auxiliary_unit_cost": 0.0,
                    "labor_unit_cost": 0.0,
                    "inclusive_unit_cost": 0.0,
                })
                Material.create(vals)


class AbrojCostProject(models.Model):
    _inherit = "abroj.cost.project"

    @api.model
    def default_get(self, fields_list):
        self.env["abroj.cost.defaults"].ensure_for_company(self.env.company)
        return super().default_get(fields_list)


class ResCompany(models.Model):
    _inherit = "res.company"

    abroj_project_costing_enabled = fields.Boolean(
        string="إظهار أبرج | تكاليف المشاريع",
        default=False,
        help="يظهر تطبيق أبرج | تكاليف المشاريع فقط عند اختيار هذه الشركة في رأس أودو.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        defaults = self.env["abroj.cost.defaults"].sudo()
        for company in companies:
            defaults.ensure_for_company(company)
        return companies
