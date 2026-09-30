#!/usr/bin/env bash
# Static guard used by PR CI whenever QA deployment source changes.
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/../.." && pwd -P)"
cd "$repo_root"

for script in \
    ops/qa/baseer-qa-approve-release \
    ops/qa/baseer-qa-deploy \
    ops/qa/baseer-qa-release-poller \
    ops/qa/install-qa-release-poller.sh; do
    bash -n "$script"
done

for policy in ops/qa/release-policies/*.env; do
    [ -f "$policy" ] || continue
    awk -F= '
        BEGIN { release=commit=modules=0; valid=1 }
        /^[[:space:]]*($|#)/ { next }
        NF != 2 { valid=0; next }
        $1 == "RELEASE_ID" { release++; if ($2 !~ /^[a-z0-9][a-z0-9-]{2,63}$/) valid=0; next }
        $1 == "COMMIT" { commit++; if ($2 !~ /^[a-f0-9]{40}$/) valid=0; next }
        $1 == "MODULES" {
            modules++
            if ($2 !~ /^baseer_[a-z0-9_]+(,baseer_[a-z0-9_]+)*$/) { valid=0; next }
            count=split($2, values, ",")
            for (item = 1; item <= count; item++) {
                if (seen[values[item]]++) valid=0
            }
            next
        }
        { valid=0 }
        END { exit !(valid && release == 1 && commit == 1 && modules == 1) }
    ' "$policy" || { printf 'invalid QA release policy: %s\n' "$policy" >&2; exit 1; }
done

printf 'QA_DEPLOY_SOURCE=PASS\n'
