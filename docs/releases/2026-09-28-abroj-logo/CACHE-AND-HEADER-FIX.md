# Logo presentation correction

User's mobile screenshot after the first release still shows the previous mark in blue. Expected: approved new logo in white in the hero header and blue in the footer.

## Evidence and bounded change

- Previous static URL sends `Cache-Control: public, max-age=604800`; reusing it allows previously cached logo bytes for seven days. Origin bytes already match the new approved master. The screenshot plus unchanged URL is consistent with a warm-client image cache; the user's browser cache was not inspected.
- The previous release removed the header-only white filter, causing the observed blue header (confirmed by fresh mobile browser computed style `filter: none`).
- `abroj_website 19.0.1.5.3` adds `abroj-logo-approved-20260928.png`, byte-identical to the approved master SHA256 `a7356f89ccf9040d20f75f8be108d711192d0e14cfe7e76efa55e12aa76864ab`.
- Both homepage image references use the new filename. The old URL remains available for existing secondary-page consumers.
- Restore `brightness(0) invert(1)` ONLY for `.abroj-v2__brand img`; footer source colors are unchanged. No image geometry, alpha, corporate spelling, page layout, native-logo migration, website settings, or other module changes.

## Verification and release boundary

Reuses the current architecture/source-drift review; source impact remains LOCAL. Independent Alpha reviewer returned code GO after checking hash, both image references, filter selector isolation, XML/manifest, and diff whitespace. Fresh mobile before-check at 390px confirms old URL in both positions and no header filter. Post-release checks must prove new URL in both places, images loaded, white computed header filter, unfiltered blue footer, and exact new asset hash. Dedicated headless mobile test is used because the in-app browser tool cannot start; it does not attach to user tabs.

Release through reviewed PRs and existing GitHub Actions only. No direct live-file edit. Financial/load tests are not repeated for this bounded visual correction. Existing protected wrapper provides recovery pair and rollback.
