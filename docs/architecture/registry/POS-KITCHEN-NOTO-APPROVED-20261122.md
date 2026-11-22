# Noto Sans Arabic — approved kitchen font, 2026-11-22

Owner explicitly approved Noto Sans Arabic after QA comparison4050 ("تمام اعتمده"). This supersedes the Segoe UI comparison/preference candidate d6499e311. Approved weights: body text and tracking digits500; product names/quantities600; titles/headings/labels700. Font sizes, business content, paper width and agent remain unchanged. Source candidate on codex/qa-kitchen-noto-20261122, baseline official/main30a3202ac. No Live deployment is implied by this approval record.

## Evidence

- Official notofonts/arabic release NotoSansArabic-v2.012.zip; static googlefonts/ttf Medium, SemiBold, Bold plus OFL.txt. No application dependency added; no Windows proprietary fonts copied.
- Font OS/2 weights verified500/600/700. Rendering used actual Odoo Linux/Qt `_render_kitchen_jpeg` and production JFIF normalization, with FONTCONFIG_FILE scoped only to the QA shell/render process. Fonts/config live under `/tmp/baseer-noto-qa-20261122`; existing service/global font settings unchanged.
- Actual Qt PDF font names independently checked: NotoSansArabic-Medium, NotoSansArabic-SemiBold, NotoSansArabic-Bold; no substituted font names. CSS alone/fc-match alone was not treated as render proof.
- JPEG576x801,84221 bytes,SHA25610021f6241138969a8d95b9eb1ef9e0610d0c6acf7c769d5dcf849fa6adcb7dc. Arabic, ASCII digits/phone and ending visually reviewed before print.
- QA4050 DONE,attempt1,copies1,PSS7-80mm; Windowsjob53 printing→unobserved plus Odoo acknowledgement. Synthetic document, no sale/source order/session. Test identity13 revoked and its newly discovered printers deactivated after execution. Owner approved the font afterward; this does not claim universal hardware reliability.
- Unmodified QA agent1.5.22 binary SHA2562c8c62b7abdc9f7e58df6d1d167e84cf4c114095381cb6e59fe0a673c8c8ba28. No agent source/file changes. Targeted XML parse and diff checks passed.

Artifacts: output/noto-qa/font-proof.json,font-proof.pdf,noto.jpg,font-manifest.json,fonts/OFL.txt,print/result.json,print/diagnostics/events.jsonl,REVIEW.md. These are isolated QA evidence; no secret/config file is part of the source commit.

## Deployment boundary

The QWeb font/weight preference is accepted. Continuous server rendering still requires the same licensed static faces to be provisioned durably through the approved Git/release deployment path; the temporary per-process QA setup is not a production installation. Preserve the OFL notice and pin font hashes when packaging. Do not rely on silent fallback when releasing. Live deployment and agent distribution have not been performed by this font acceptance.

Official source/license: https://github.com/notofonts/arabic/releases/tag/NotoSansArabic-v2.012 and https://github.com/notofonts/arabic/blob/main/OFL.txt .
