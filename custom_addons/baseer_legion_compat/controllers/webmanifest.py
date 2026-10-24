"""Present Baseer identity through Odoo's existing installable-app contract."""

from odoo.addons.web.controllers.webmanifest import WebManifest
from odoo.http import request

BRAND_PRIMARY = "#5B04A0"
ICON_ROOT = "/baseer_legion_compat/static/src/img"


class BaseerWebManifest(WebManifest):
    def _get_webmanifest(self):
        manifest = super()._get_webmanifest()
        # Respect an explicitly configured application name.
        if manifest.get("name") == "Odoo":
            manifest["name"] = (
                "بصير" if (request.env.lang or "").startswith("ar") else "Baseer"
            )
        manifest.update(
            short_name=manifest["name"],
            theme_color=BRAND_PRIMARY,
            background_color=BRAND_PRIMARY,
            icons=[
                {"src": f"{ICON_ROOT}/baseer-icon-{size}.png", "sizes": f"{size}x{size}",
                 "type": "image/png", "purpose": "any"}
                for size in (192, 512)
            ],
        )
        return manifest

    def _icon_path(self):
        return f"{ICON_ROOT.lstrip('/')}/baseer-icon-192.png"
