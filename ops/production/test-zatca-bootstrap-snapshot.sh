#!/usr/bin/env bash
# Focused guard proof: Saudi EDI's two stored computations may advance only
# write_date; every protected count, ID sum and business fingerprint remains
# immutable.  This test never contacts Docker or a database.
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
wrapper="$script_dir/baseer-production-deploy"
work="$(mktemp -d -t baseer-zatca-snapshot.XXXXXXXX)"
trap 'rm -rf -- "$work"' EXIT

sed -n '/^verify_zatca_bootstrap_recompute() {/,/^}/p' "$wrapper" > "$work/function.sh"
backup="$work"
source "$work/function.sh"

cat > "$work/protected-before.json" <<'JSON'
{"account.move":{"n":2,"ids":3,"w":"before","f":"move-hash"},"res.partner.non_user":{"n":3,"ids":9,"w":"before","f":"partner-hash"},"stock.move":{"n":5,"ids":15,"w":"same"}}
JSON
cat > "$work/protected-after.json" <<'JSON'
{"account.move":{"n":2,"ids":3,"w":"after","f":"move-hash"},"res.partner.non_user":{"n":3,"ids":9,"w":"after","f":"partner-hash"},"stock.move":{"n":5,"ids":15,"w":"same"}}
JSON
verify_zatca_bootstrap_recompute

cat > "$work/protected-after.json" <<'JSON'
{"account.move":{"n":2,"ids":3,"w":"after","f":"tampered"},"res.partner.non_user":{"n":3,"ids":9,"w":"after","f":"partner-hash"},"stock.move":{"n":5,"ids":15,"w":"same"}}
JSON
if verify_zatca_bootstrap_recompute; then
    printf '%s\n' 'tampered account.move fingerprint was accepted' >&2
    exit 1
fi

cat > "$work/protected-after.json" <<'JSON'
{"account.move":{"n":2,"ids":3,"w":"after","f":"move-hash"},"res.partner.non_user":{"n":3,"ids":9,"w":"after","f":"tampered"},"stock.move":{"n":5,"ids":15,"w":"same"}}
JSON
if verify_zatca_bootstrap_recompute; then
    printf '%s\n' 'tampered partner fingerprint was accepted' >&2
    exit 1
fi

cat > "$work/protected-after.json" <<'JSON'
{"account.move":{"n":2,"ids":3,"w":"after","f":"move-hash"},"res.partner.non_user":{"n":3,"ids":9,"w":"after","f":"partner-hash"},"stock.move":{"n":5,"ids":15,"w":"changed"}}
JSON
if verify_zatca_bootstrap_recompute; then
    printf '%s\n' 'write_date change outside the reviewed models was accepted' >&2
    exit 1
fi

printf '%s\n' 'ZATCA_BOOTSTRAP_SNAPSHOT_GUARD=PASS'
