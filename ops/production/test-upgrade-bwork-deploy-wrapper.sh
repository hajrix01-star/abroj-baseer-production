#!/bin/bash
# Isolated control-flow/file tests. Root ownership, filesystem modes and flock
# are mocked for portability (including Git Bash); NO host/root acceptance claim.
set -Eeuo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
sut="$script_dir/upgrade-bwork-deploy-wrapper.sh"
test_dir="$(mktemp -d -t bwork-wrapper-test.XXXXXXXX)"
cleanup() {
    case "$test_dir" in */bwork-wrapper-test.????????) [ -d "$test_dir" ] && rm -rf -- "$test_dir" ;; *) exit 1 ;; esac
}
trap cleanup EXIT

fixture_case() (
    case_name=$1 action=$2
    case_dir="$test_dir/$case_name"
    mkdir -p "$case_dir/live/releases/baseline" "$case_dir/sbin" "$case_dir/source"
    readonly BASE="$case_dir/live" CURRENT="$case_dir/live/releases/baseline"
    readonly TARGET="$case_dir/sbin/baseer-production-deploy" LOCK="$case_dir/deploy.lock"
    readonly BACKUP_ROOT="$BASE/control-plane-backups" CANDIDATE="$case_dir/source/baseer-production-deploy"
    readonly LIVE_SOURCE=b3e6547fdf0c2e4f1392fcdc4f9a55e6fb877bce
    printf '#!/bin/bash\n# old isolated fixture\nexit 0\n' > "$TARGET"
    printf '#!/bin/bash\n# new isolated fixture\nexit 0\n' > "$CANDIDATE"
    readonly OLD_SHA="$(sha256sum "$TARGET" | cut -d ' ' -f 1)"
    readonly NEW_SHA="$(sha256sum "$CANDIDATE" | cut -d ' ' -f 1)"
    printf '%s\n' "$LIVE_SOURCE" > "$CURRENT/RELEASE_COMMIT"
    : > "$LOCK"
    replacement_started=0 backup='' pending=''
    # Load actual functions only, with all fixed filesystem constants mapped to
    # this NEW synthetic directory. Never execute production top-level paths.
    source <(sed -n '/^digest()/,$p' "$sut" | sed '/^main "\$@"$/d')
    id() { if [ "$case_name" = nonroot ]; then printf '1000\n'; else printf '0\n'; fi; }
    stat() {
        local format=$2 path=${@: -1}
        case "$format" in
            '%u:%g') if [ "$case_name" = wrongowner ] && [ "$path" = "$TARGET" ]; then printf '1000:1000\n'; else printf '0:0\n'; fi ;;
            '%u:%g:%a')
                if [[ "$path" == */previous-wrapper ]]; then printf '0:0:600\n'
                elif [ "$case_name" = wrongmode ]; then printf '0:0:755\n'
                else printf '0:0:750\n'; fi ;;
            '%a') if [[ "$path" == "$BACKUP_ROOT"* ]]; then printf '700\n'; else printf '755\n'; fi ;;
            '%d:%i')
                if [ "$case_name" = lockinode ] && [ "$path" = /proc/self/fd/9 ]; then printf '1:2\n'
                elif [ "$case_name" = lockafter ] && [ -e "$case_dir/locked" ] && [ "$path" = "$LOCK" ]; then printf '1:2\n'
                else printf '1:1\n'; fi ;;
            *) command stat "$@" ;;
        esac
    }
    flock() { : > "$case_dir/locked"; [ "$case_name" != locked ]; }
    sync() { printf '%s\n' "${@: -1}" >> "$case_dir/sync-events"; }
    install() {
        local args=() directory=0
        while [ "$#" -gt 0 ]; do
            case "$1" in -d) directory=1; shift ;; -o|-g|-m) shift 2 ;; --) shift ;; *) args+=("$1"); shift ;; esac
        done
        if [ "$directory" -eq 1 ]; then command mkdir -p -- "${args[@]}"; else command cp -- "${args[@]}"; fi
    }
    chmod() { :; } # Windows filesystem mode changes are not host acceptance.
    digest() {
        local value; value="$(sha256sum -- "$1" | cut -d ' ' -f 1)"
        if [ "$case_name" = rollback ] && [ "$1" = "$TARGET" ] \
            && [ "$value" = "$NEW_SHA" ] && [ ! -e "$case_dir/posthash-injected" ]; then
            : > "$case_dir/posthash-injected"
            printf '%064d\n' 0
        else printf '%s\n' "$value"; fi
    }
    case "$case_name" in
        unknownhash) printf 'unknown wrapper\n' > "$TARGET" ;;
        wrongsource) printf '%040d\n' 0 > "$CURRENT/RELEASE_COMMIT" ;;
        wrongcandidate) printf '# changed\n' >> "$CANDIDATE" ;;
        already) cp "$CANDIDATE" "$TARGET"; printf '%040d\n' 0 > "$CURRENT/RELEASE_COMMIT" ;;
    esac
    main "$action"
)

pass=0
for spec in 'dry:--dry-run' 'apply:--apply' 'already:--apply' 'rollback:--apply' \
    'unknownhash:--apply' 'wrongsource:--apply' 'wrongcandidate:--apply' \
    'wrongmode:--apply' 'wrongowner:--apply' 'locked:--apply' 'lockinode:--apply' \
    'lockafter:--apply' 'nonroot:--apply'; do
    name=${spec%%:*}; action=${spec#*:}; log="$test_dir/$name.log"
    # Do not invoke fixture_case in an if/OR expression: that disables errexit
    # inside Bash functions and would invalidate the actual rollback exercise.
    set +e
    ( set -e; fixture_case "$name" "$action" ) > "$log" 2>&1
    status=$?
    set -e
    case "$name:$status" in
        dry:0|apply:0|already:0) ;;
        dry:*|apply:*|already:*) cat "$log" >&2; exit 1 ;;
    esac
    case "$name" in
        dry)
            [ "$status" -eq 0 ]; grep -Fxq 'WRAPPER_UPGRADE=DRY_RUN' "$log"
            [ ! -e "$test_dir/$name/live/control-plane-backups" ] ;;
        apply)
            [ "$status" -eq 0 ]; grep -Fxq 'WRAPPER_UPGRADE=GO' "$log"
            cmp "$test_dir/$name/sbin/baseer-production-deploy" "$test_dir/$name/source/baseer-production-deploy"
            [ "$(wc -l < "$test_dir/$name/sync-events")" -eq 6 ]
            [ "$(find "$test_dir/$name/live/control-plane-backups" -name previous-wrapper | wc -l)" -eq 1 ] ;;
        already)
            [ "$status" -eq 0 ]; grep -Fxq 'WRAPPER_UPGRADE=ALREADY_CURRENT' "$log"
            [ ! -e "$test_dir/$name/live/control-plane-backups" ] ;;
        rollback)
            [ "$status" -ne 0 ]; grep -Fxq 'WRAPPER_ROLLBACK=GO' "$log"
            old_backup="$(find "$test_dir/$name/live/control-plane-backups" -name previous-wrapper)"
            [ "$(wc -l < "$test_dir/$name/sync-events")" -eq 8 ]
            cmp "$test_dir/$name/sbin/baseer-production-deploy" "$old_backup" ;;
        *) [ "$status" -ne 0 ]; grep -Fq 'WRAPPER_UPGRADE=FAILED' "$log"
            [ ! -e "$test_dir/$name/live/control-plane-backups" ] ;;
    esac
    pass=$((pass+1)); printf 'PASS %s\n' "$name"
done

# Fixed production constants/policy stay authoritative; fixtures above do not
# change the production script or normalize unknown installed wrapper hashes.
grep -Fxq 'readonly TARGET=/usr/local/sbin/baseer-production-deploy' "$sut"
grep -Fxq 'readonly OLD_SHA=02947f09fabe2f276266ef567be689311a94dc904835975c3e26270ce96f9587' "$sut"
grep -Fxq 'readonly NEW_SHA=d3c11d43215781b77c147c3ba6a470254c4e9fb42ee1bde82f3eab0ee9a0e3b7' "$sut"
grep -Fxq 'readonly LOCK=/var/lock/baseer-production-deploy.lock' "$sut"
[ "$(wc -l < "$script_dir/release-policies/baseer-2026-10-21-bwork-production.env")" -eq 3 ]
grep -Fxq 'COMMIT=81fdd415521670b8c7ad681e97dd583e6f9c85e0' "$script_dir/release-policies/baseer-2026-10-21-bwork-production.env"
printf 'PASS %s isolated wrapper cases; mocked root metadata/flock/sync, no host or database\n' "$pass"
