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
filestore_capture_enospc() (
    load_guard
    QA_BASE="$test_dir/filestore-enospc"
    old_release="$QA_BASE/old"
    backup="$QA_BASE/backup"
    QA_DB_CONTAINER=qa-db QA_ODOO_VOLUME=qa-volume QA_DATABASE=baseer_qa
    ODOO_SERVICE=odoo
    mkdir -p "$old_release" "$backup"
    release_switched=0 database_mutated=0 service_quiesced=1 phase_guard_active=1
    compose_cmd() { printf '%s\n' "$*" >> "$QA_BASE/compose.trace"; }
    wait_for_login() { return 0; }
    docker() {
        printf '%s\n' "$*" >> "$QA_BASE/docker.trace"
        if [ "$1" = exec ]; then printf 'valid database dump'; return 0; fi
        [ "$1" = run ] && return 28
        return 1
    }
    trap rollback ERR
    capture_recovery_pair
)

# Invoke restore_pair as rollback does: the OR-list intentionally disables
# errexit in Bash. Every failing step must therefore have an explicit guard.
restore_step_failure() (
    load_guard
    local mode=$1
    QA_BASE="$test_dir/restore-$mode"
    old_release="$QA_BASE/old"
    backup="$QA_BASE/backup"
    QA_DB_CONTAINER=qa-db QA_ODOO_VOLUME=qa-volume QA_DATABASE=baseer_qa
    ODOO_SERVICE=odoo
    mkdir -p "$old_release" "$backup"
    : > "$backup/database.dump"
    sha256sum() {
        printf 'checksum\n' >> "$QA_BASE/restore.trace"
        [ "$mode" != checksum ]
    }
    compose_cmd() {
        printf 'compose %s\n' "$*" >> "$QA_BASE/restore.trace"
        [ "$mode" != stop ] || [ "$1" != stop ]
    }
    docker() {
        printf 'docker %s\n' "$*" >> "$QA_BASE/restore.trace"
        case "$mode:$*" in
            dropdb:*dropdb*|createdb:*createdb*|pg_restore:*pg_restore*|filestore_restore:run*) return 28 ;;
        esac
        return 0
    }
    if restore_pair; then
        printf 'restore unexpectedly succeeded after %s failure\n' "$mode" >&2
        return 1
    fi
    case "$mode" in
        checksum) ! grep -Fq 'compose ' "$QA_BASE/restore.trace" && ! grep -Fq 'docker ' "$QA_BASE/restore.trace" ;;
        stop) ! grep -Fq 'docker ' "$QA_BASE/restore.trace" ;;
        dropdb) ! grep -Fq 'createdb ' "$QA_BASE/restore.trace" ;;
        createdb) ! grep -Fq 'pg_restore ' "$QA_BASE/restore.trace" ;;
        pg_restore) ! grep -Fq 'docker run ' "$QA_BASE/restore.trace" ;;
    esac
)

rollback_restore_failure() (
    load_guard
    local mode=$1
    QA_BASE="$test_dir/rollback-$mode"
    old_release="$QA_BASE/old"
    backup="$QA_BASE/backup"
    QA_DB_CONTAINER=qa-db QA_ODOO_VOLUME=qa-volume QA_DATABASE=baseer_qa
    ODOO_SERVICE=odoo
    mkdir -p "$old_release" "$backup"
    : > "$backup/database.dump"
    release_switched=1 database_mutated=1 service_quiesced=1
    sha256sum() { [ "$mode" != checksum ]; }
    compose_cmd() {
        printf '%s\n' "$*" >> "$QA_BASE/compose.trace"
        [ "$mode" != stop ] || [ "$1" != stop ]
    }
    docker() {
        printf '%s\n' "$*" >> "$QA_BASE/docker.trace"
        case "$mode:$*" in
            dropdb:*dropdb*|pg_restore:*pg_restore*) return 28 ;;
        esac
        return 0
    }
    ln() { printf '%s\n' "$*" >> "$QA_BASE/link.trace"; }
    wait_for_login() { printf 'login\n' >> "$QA_BASE/compose.trace"; }
    rollback 1
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
expect_failed filestore-enospc 'QA filestore backup failed' filestore_capture_enospc
expect_failed smoke 'fatal QA smoke log entry' smoke_failure
expect_failed smoke-read 'cannot scan QA smoke log' smoke_failure unreadable
for step in checksum stop dropdb createdb pg_restore filestore_restore; do
    restore_step_failure "$step"
done
for mode in checksum stop dropdb pg_restore; do
    expect_failed "rollback-$mode" 'QA_DEPLOY=ROLLBACK_FAILED' rollback_restore_failure "$mode"
done

grep -Fq 'QA_DEPLOY=ROLLED_BACK' "$test_dir/backup-recheck/backup/result.env"
grep -Fq 'QA_DEPLOY=ROLLED_BACK' "$test_dir/backup-capture/backup/result.env"
grep -Fq 'up -d odoo' "$test_dir/backup-capture/compose.trace"
! grep -Fq 'QA_DEPLOY=GO' "$test_dir/backup-capture/backup/result.env"
grep -Fq 'exec qa-db' "$test_dir/filestore-enospc/docker.trace"
grep -Fq 'run --rm' "$test_dir/filestore-enospc/docker.trace"
grep -Fq 'QA_DEPLOY=ROLLED_BACK' "$test_dir/filestore-enospc/backup/result.env"
grep -Fq 'up -d odoo' "$test_dir/filestore-enospc/compose.trace"
! grep -Fq 'QA_DEPLOY=GO' "$test_dir/filestore-enospc/backup/result.env"
for mode in checksum stop dropdb pg_restore; do
    grep -Fq 'QA_DEPLOY=ROLLBACK_FAILED' "$test_dir/rollback-$mode/backup/result.env"
    ! grep -Fq 'up -d odoo' "$test_dir/rollback-$mode/compose.trace"
    ! grep -Fq 'login' "$test_dir/rollback-$mode/compose.trace"
done
! test -e "$test_dir/rollback-checksum/docker.trace"
! test -e "$test_dir/rollback-stop/docker.trace"
! test -e "$test_dir/rollback-stop/link.trace"
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
grep -Fq 'compose_cmd logs --since "$smoke_since" --no-color --tail=300' "$deploy"

printf 'QA_DEPLOY_GUARD_TESTS=PASS\n'
