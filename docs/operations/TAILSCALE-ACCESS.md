# Tailscale access — 2026-09-10 Riyadh

Original: https://desktop-cvc68i5.tail938958.ts.net:18069/odoo

Tailscale Serve background HTTPS18069 proxies only to http://127.0.0.1:18069 (MAIN/baseer_dev). Enabled on user request for original access link; private tailnet only, no Funnel. Existing HTTPS18070 QA and other mappings retained. HTTPS /web/login returned200 with certificate verification. No application source/database changes. Host and client Tailscale must be connected; host must remain running.

Disable this mapping only: `tailscale serve --https=18069 off`.
