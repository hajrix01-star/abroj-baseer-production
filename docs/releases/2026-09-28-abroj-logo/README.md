# Approved ABROJ logo — scoped live promotion

Owner requested promotion of the approved QA logo only, then continuation of a separate local motion draft. No motion, experimental mark, QA page layout or business data is part of this release.

## Source and impact

- Base: `0ce8f592d694fbbb47bbd5229bdc264bf2c54c3d`; previous Live: `1a97dc3b16b72dd458d0e999260650c0ae4e7ebc`.
- Architecture: LOCAL identity change inside `abroj_website`, existing protected release pipeline unchanged. Existing map in `docs/architecture/registry/INDEX.md` is reused.
- Flow: approved PNG -> static homepage header/footer and contact-page references; XML data -> native `website.default_website.logo` -> native header image endpoint. Other website records and company logos are not targeted by the new data file.
- Native logo is set by a one-time post-migration because its existing external ID is protected with `noupdate`. XML handles new installations. Both use the native `image_no_postprocess` context to preserve the approved high-resolution PNG bytes; no global image setting changes. No manual copy or direct execution in a live release is used.
- Module `19.0.1.5.2`: same static filename to preserve existing consumers, approved transparent all-blue wordmark with corrected jeem dot and supervision tagline; remove only the custom header's white-color filter.
- PNG SHA-256: `a7356f89ccf9040d20f75f8be108d711192d0e14cfe7e76efa55e12aa76864ab` (2171×724 RGBA).

## Bounded verification

Master hash, alpha, jeem-dot pixel, XML target/field, manifest version and syntax, and `git diff --check` verified locally. An independent release reviewer compared 1199 live runtime source files to the previous Live commit: no missing, extra or modified files; no runtime difference from that commit to this base. Database container healthy and website login HTTP 200 before release.

No financial, concurrency or load tests are repeated for this image-only change. Native protected release captures paired database/filestore backup and protects business-table snapshots. Rollback uses that protected workflow's previous source and paired recovery set. Public static/native image hash and homepage/contact HTTP checks are required after deployment; do not treat this preflight as proof of publication.

Brand artwork is the user-approved master from QA. Source provenance and existing company identity are unchanged. No new font, package, model, permission, domain, endpoint, deployment privilege or external media dependency.
