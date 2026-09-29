# Arabic UI proof

Read-only browser verification on 2026-09-14 used the authenticated isolated demo UI at `http://127.0.0.1:18087`.

- The target form (`/odoo/action-835/new`) displays: `أهداف التقويم الحراري`, `الشركة`, `السنة`, `الشهر`, `يوم الأسبوع`, `المبلغ المستهدف`, and `نشط`.
- The occasion form (`/odoo/action-834/new`) displays: `المناسبات الرسمية`, `الاسم العربي`, `الاسم الإنجليزي`, `النوع` = `عطلة رسمية`, and `الحالة` = `تقديري`.
- No form was saved and no data was entered.

The candidate `.3` differs from `.2` only in `RELEASE-RECEIPT.md`; its source/UI blobs are therefore identical to this visual proof. The binary verification in `CANDIDATE-PROVENANCE-52e9ff5.md` independently proves the tagged `.3` payload.
