# Segoe UI kitchen comparison — QA only, 2026-11-22

Owner confirmed paper4048 complete, one copy, Arabic/digits clear; requested Segoe UI from Odoo and one comparison print without changing agent. Small presentation delta: prepend Segoe UI to the existing QWeb font stack, preserving all other CSS/content. Baseline official/main30a3202ac; isolated branch codex/qa-kitchen-segoe-20261122.

The actual HTTPS QA endpoint still routes to baseer_qa_20261023/18134. `fc-match 'Segoe UI'` there resolves to DejaVu Sans; Segoe is NOT installed in the Linux container. Merely adding its CSS name would not prove Segoe output. No deployed module files, routing or existing DB views changed.

Comparison uses the immutable synthetic Odoo HTML from4047, changing only that font declaration. Windows Chrome157.0.8103.40 renders baseline and candidate with identical renderer/viewport576. CDP platform-font evidence: baseline CSS falls back to Arial on Windows; candidate uses actual Segoe UI and SegoeUI-Bold for Arabic, Latin and digits. No font files copied. Both Windows images576x721. This isolates the font on Windows, but comparison with earlier Linux Qt paper also changes rendering engine; it is not production Qt acceptance.

Candidate JPEG85054 bytes, SHA256 e430800224e647e0367368eba19bad247dbd3e897c5e218505e7a52332357939. Saved in a new QA job with its frozen Odoo HTML after the normal server image validator; no source sale/order/session. QA4049 DONE, attempt1,copies1, PSS7-80mm. Temporary identity12 revoked and its new printer records deactivated after execution. No second print, Live changes or agent updates. Same QA agent binary SHA256 2c8c62b7abdc9f7e58df6d1d167e84cf4c114095381cb6e59fe0a673c8c8ba28.

Evidence: output/segoe-qa/font-proof.json, baseline/segoe PNG/JPEG, print/result.json and sanitized diagnostic journal/support ZIP. One-line source diff and XML parse checked. Physical comparison pending owner feedback. This branch is a font preference candidate, not a deployed server font installation.

Continuous Linux/Odoo raster output using Segoe requires a legitimate server font installation or a separately approved rendering solution; no permanent rendering service introduced for this comparison. Microsoft permits rendered text graphics while restricting copying Windows fonts to other servers without additional rights: https://learn.microsoft.com/en-us/typography/fonts/font-faq .
