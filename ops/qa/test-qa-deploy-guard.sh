#!/usr/bin/env bash
# Isolated function tests: no QA host, Docker daemon, or live database required.
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
deploy="$script_dir/baseer-qa-deploy"
test_dir="$(mktemp -d)"

load_guard() {
    # Stop before the wrapper's first executable top-level statement.
    # shellcheck disable=SC1090
    source <(sed '/^require_root$/,$d' "$deploy")
}

stub_capacity() {
    release_apparent_bytes() { printf '100\n'; }
    release_entry_count() { printf '50\n'; }
    database_apparent_bytes() { printf '200\n'; }
    filestore_apparent_bytes() { printf '300\n'; }
    qa_available_bytes() { printf '2000000000\n'; }
    qa_available_inodes() { printf '10000\n'; }
}

expect_failed() {
    local name=$1 expected=$2
    shift 2
    if "$@" > "$test_dir/$name.log" 2>&1; then
        printf 'unexpected success: %s\n' "$name" >&2
        exit 1
    fi
    if [ -n "$expected" ]; then
        grep -Fq "$expected" "$test_dir/$name.log" || {
            printf 'wrong failure: %s\n' "$name" >&2
            sed -n '1,15p' "$test_dir/$name.log" >&2
            exit 1
        }
    fi
}

low_bytes() (
    load_guard
    stub_capacity
    qa_available_bytes() { printf '1073742423\n'; } # one byte below 2*100+200+300+1GiB
    capacity_guard prefetch
)
low_inodes() (
    load_guard
    stub_capacity
    qa_available_inodes() { printf '4145\n'; } # one below 50+4096
    capacity_guard prefetch
)
failed_estimate() (
    load_guard
    stub_capacity
    database_apparent_bytes() { return 28; }
    capacity_guard prefetch
)
backup_recheck_failure() (
    load_guard
    stub_capacity
    QA_BASE="$test_dir/backup-recheck"
    old_release="$QA_BASE/old"
    backup="$QA_BASE/backup"
    mkdir -p "$old_release" "$backup"
    release_switched=0 database_mutated=0 service_quiesced=0 phase_guard_active=1
    qa_available_bytes() { printf '1073742323\n'; } # below 200+300+1GiB
    capacity_guard backup
)
backup_capture_failure() (
    load_guard
    QA_BASE="$test_dir/backup-capture"
    old_release="$QA_BASE/old"
    backup="$QA_BASE/backup"
    QA_DB_CONTAINER=qa-db QA_ODOO_VOLUME=qa-volume QA_DATABASE=baseer_qa
    ODOO_SERVICE=odoo
    mkdir -p "$old_release" "$backup"
    release_switched=0 database_mutated=0 service_quiesced=1 phase_guard_active=1
    compose_cmd() { printf '%s\n' "$*" >> "$QA_BASE/compose.trace"; }
    wait_for_login() { return 0; }
    docker() { return 28; }
    trap rollback ERR
    capture_recovery_pair
)
smoke_failure() (
    load_guard
    local mode=${1:-fatal}
    QA_BASE="$test_dir/smoke-$mode"
    old_release="$QA_BASE/old"
    backup="$QA_BASE/backup"
    ODOO_SERVICE=odoo
    mkdir -p "$old_release" "$backup"
    : > "$QA_BASE/current"
    if [ "$mode" = fatal ]; then
        printf 'FATAL: boot failed\n' > "$backup/odoo-smoke.log"
    fi
    release_switched=1 database_mutated=0 service_quiesced=1 phase_guard_active=1
    compose_cmd() { printf '%s\n' "$*" >> "$QA_BASE/compose.trace"; }
    ln() { printf '%s\n' "$*" >> "$QA_BASE/link.trace"; }
    wait_for_login() { return 0; }
    verify_smoke_log
)

expect_failed low-bytes 'insufficient QA free bytes before prefetch' low_bytes
expect_failed low-inodes 'insufficient QA free inodes before prefetch' low_inodes
expect_failed estimate 'cannot estimate QA database size' failed_estimate
expect_failed backup-recheck 'insufficient QA free bytes before backup' backup_recheck_failure
expect_failed backup-capture '' backup_capture_failure
expect_failed smoke 'fatal QA smoke log entry' smoke_failure
expect_failed smoke-read 'cannot scan QA smoke log' smoke_failure unreadable

grep -Fq 'QA_DEPLOY=ROLLED_BACK' "$test_dir/backup-recheck/backup/result.env"
grep -Fq 'QA_DEPLOY=ROLLED_BACK' "$test_dir/backup-capture/backup/result.env"
grep -Fq 'up -d odoo' "$test_dir/backup-capture/compose.trace"
! grep -Fq 'QA_DEPLOY=GO' "$test_dir/backup-capture/backup/result.env"
for mode in fatal unreadable; do
    grep -Fq 'QA_DEPLOY=ROLLED_BACK' "$test_dir/smoke-$mode/backup/result.env"
    grep -Fq 'up -d odoo' "$test_dir/smoke-$mode/compose.trace"
    grep -Fq -- "-sfn $test_dir/smoke-$mode/old $test_dir/smoke-$mode/current" "$test_dir/smoke-$mode/link.trace"
    ! grep -Fq 'QA_DEPLOY=GO' "$test_dir/smoke-$mode/backup/result.env"
done

# Guard ordering is part of the contract, not just a helper's behavior.
prefetch_line="$(grep -n '^capacity_guard prefetch$' "$deploy" | cut -d: -f1)"
fetch_line="$(grep -n '^git init --bare' "$deploy" | cut -d: -f1)"
backup_line="$(grep -n '^capacity_guard backup$' "$deploy" | cut -d: -f1)"
stop_line="$(grep -n '^compose_cmd stop "\$ODOO_SERVICE"$' "$deploy" | cut -d: -f1)"
(( prefetch_line < fetch_line && backup_line < stop_line ))

printf 'QA_DEPLOY_GUARD_TESTS=PASS\n'
