# Abroj Website Theme — v1

Custom Arabic-first Odoo Website theme for **Abroj Integrated Construction**.

## Target
- Odoo 19 Community
- Website app installed

## Included in v1
- Custom homepage replacing the default Odoo homepage content
- Arabic RTL layout
- Responsive desktop / tablet / mobile styling
- Hero section focused on villas and residential construction
- Services: residential construction, renovation, retail fit-out, HVAC
- X-ray technical section for hidden building systems
- Work-type showcase without inventing completed projects
- Execution-process section
- CTA linked to `/contactus`
- Lightweight scroll-reveal motion
- Optimized WebP visual assets

## Install
1. Copy the `theme_abroj` folder into your custom addons path.
2. Restart Odoo.
3. Update Apps List.
4. Search for **Abroj Website Theme** and install it.
5. Open Website and review the homepage.

## Font
v1 uses IBM Plex Sans Arabic / IBM Plex Sans because they are web-safe to deploy without bundling a proprietary font license. If a licensed DIN Next Arabic webfont is available, replace the font declaration in `static/src/scss/abroj.scss`.

## Next build stage
- Dedicated service pages
- About page
- Projects CMS structure
- Quote-request form connected to CRM lead/opportunity
- Arabic / English translation structure
- Abroj final logo asset
- SEO metadata and structured data
- Odoo editable snippets for non-technical content updates
