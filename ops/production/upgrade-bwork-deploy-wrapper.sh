#!/bin/bash
# Fixed control-plane upgrade only. Default is read-only; never installs addons,
# policies, users, sudo rules, keys, approver, application config or credentials.
set -Eeuo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C
umask 077

readonly BASE=/srv/abroj-baseer-production
readonly CURRENT="$BASE/current"
readonly TARGET=/usr/local/sbin/baseer-production-deploy
readonly LOCK=/var/lock/baseer-production-deploy.lock
readonly BACKUP_ROOT="$BASE/control-plane-backups"
readonly OLD_SHA=02947f09fabe2f276266ef567be689311a94dc904835975c3e26270ce96f9587
readonly NEW_SHA=d3c11d43215781b77c147c3ba6a470254c4e9fb42ee1bde82f3eab0ee9a0e3b7
readonly LIVE_SOURCE=b3e6547fdf0c2e4f1392fcdc4f9a55e6fb877bce
readonly SCRIPT_DIR="$(dirname -- "$(realpath -m -s -- "${BASH_SOURCE[0]}")")"
readonly CANDIDATE="$SCRIPT_DIR/baseer-production-deploy"
replacement_started=0 backup='' pending=''

digest() { sha256sum -- "$1" | cut -d ' ' -f 1; }
die() {
    printf 'WRAPPER_UPGRADE=FAILED\nREASON=%s\n' "$1" >&2
    if [ "$replacement_started" -eq 1 ] || [ -n "$pending" ]; then rollback 1; fi
    exit 1
}
safe_chain() {
    local path=$1 mode
    while :; do
        [ -d "$path" ] && [ ! -L "$path" ] || die 'unsafe directory ancestor'
        [ "$(stat -c '%u:%g' -- "$path")" = 0:0 ] || die 'directory ancestor is not root-owned'
        mode="$(stat -c '%a' -- "$path")"
        (( (8#$mode & 8#022) == 0 )) || die 'directory ancestor is writable by others'
        [ "$path" != / ] || break
        path="$(dirname -- "$path")"
    done
}
safe_file() {
    local mode
    [ -f "$1" ] && [ ! -L "$1" ] || die 'unsafe regular file'
    safe_chain "$(dirname -- "$1")"
    [ "$(stat -c '%u:%g' -- "$1")" = 0:0 ] || die 'file is not root-owned'
    mode="$(stat -c '%a' -- "$1")"
    (( (8#$mode & 8#022) == 0 )) || die 'file is writable by others'
}
require_target() {
    safe_file "$TARGET"
    [ "$(stat -c '%u:%g:%a' -- "$TARGET")" = 0:0:750 ] || die 'target must be root:root 0750'
}
require_live_source() {
    local release
    # current is the existing protected release symlink; its resolved directory
    # and every physical ancestor must remain root-owned and non-symlinked.
    [ -e "$CURRENT" ] && [ "$(stat -c '%u:%g' -- "$CURRENT")" = 0:0 ] || die 'unsafe current release pointer'
    release="$(readlink -f -- "$CURRENT")"
    [[ "$release" == "$BASE/releases/"* ]] || die 'current release escaped release root'
    safe_chain "$release"
    safe_file "$release/RELEASE_COMMIT"
    [ "$(cat -- "$release/RELEASE_COMMIT")" = "$LIVE_SOURCE" ] || die 'current source is not the reviewed b3 baseline'
}
require_lock_parent() {
    local parent mode
    parent="$(dirname -- "$LOCK")"
    if [ -L "$parent" ]; then
        # The only allowed system alias is /var/lock -> /run/lock. The sticky
        # native lock directory cannot let other users replace root's lock.
        [ "$parent" = /var/lock ] && [ "$(readlink -f -- "$parent")" = /run/lock ] \
            && [ "$(stat -c '%u:%g' -- "$parent")" = 0:0 ] || die 'unsafe production lock directory alias'
        safe_chain /var
        safe_chain /run
        [ -d /run/lock ] && [ ! -L /run/lock ] \
            && [ "$(stat -c '%u:%g' -- /run/lock)" = 0:0 ] || die 'unsafe native lock directory'
        mode="$(stat -c '%a' -- /run/lock)"
        [ "$mode" = 1777 ] || (( (8#$mode & 8#022) == 0 )) || die 'unsafe native lock directory mode'
    else
        safe_chain "$parent"
    fi
}
require_lock_binding() {
    local expected=$1 mode
    require_lock_parent
    [ -f "$LOCK" ] && [ ! -L "$LOCK" ] || die 'production lock path changed'
    [ "$(stat -c '%u:%g' -- "$LOCK")" = 0:0 ] || die 'production lock ownership changed'
    mode="$(stat -c '%a' -- "$LOCK")"
    (( (8#$mode & 8#022) == 0 )) || die 'production lock permissions changed'
    [ "$(stat -c '%d:%i' -- "$LOCK")" = "$expected" ] \
        && [ "$(stat -Lc '%d:%i' -- /proc/self/fd/9)" = "$expected" ] \
        || die 'production lock inode changed'
}
rollback() {
    local status=$1 restore result=1
    trap - ERR INT TERM HUP
    set +e
    if [ "$replacement_started" -eq 1 ]; then
        restore="$(mktemp "$(dirname -- "$TARGET")/.baseer-production-deploy.rollback.XXXXXXXX")"
        if [ -n "$restore" ] && install -o root -g root -m 0750 -- "$backup/previous-wrapper" "$restore" \
            && [ "$(digest "$restore")" = "$OLD_SHA" ] && sync -f -- "$restore" \
            && mv -T -- "$restore" "$TARGET" && sync -f -- "$(dirname -- "$TARGET")" \
            && [ "$(digest "$TARGET")" = "$OLD_SHA" ] \
            && [ "$(stat -c '%u:%g:%a' -- "$TARGET")" = 0:0:750 ]; then
            result=0
        fi
        [ ! -f "${restore:-}" ] || rm -f -- "$restore"
        if [ "$result" -eq 0 ]; then printf 'WRAPPER_ROLLBACK=GO\n'; else printf 'WRAPPER_ROLLBACK=FAILED\n' >&2; fi
    fi
    [ -z "$pending" ] || [ ! -f "$pending" ] || rm -f -- "$pending"
    printf 'WRAPPER_UPGRADE=FAILED\nPRIVATE_BACKUP=%s\n' "$backup" >&2
    exit "$status"
}
main() {
    local apply=0 current_sha lock_identity
    [ "$(id -u)" -eq 0 ] || die 'root is required'
    case "$#:$*" in 0:) ;; 1:--dry-run) ;; 1:--apply) apply=1 ;; *) die 'expected no argument, --dry-run or --apply' ;; esac
    require_target
    current_sha="$(digest "$TARGET")"
    if [ "$current_sha" = "$NEW_SHA" ]; then printf 'WRAPPER_UPGRADE=ALREADY_CURRENT\n'; return; fi
    [ "$current_sha" = "$OLD_SHA" ] || die 'unexpected installed wrapper hash'
    safe_file "$CANDIDATE"
    [ "$(digest "$CANDIDATE")" = "$NEW_SHA" ] || die 'candidate is not the exact reviewed raw Git LF blob'
    /bin/bash -n "$CANDIDATE" || die 'candidate shell syntax failed'
    require_live_source
    # Reuse the existing wrapper's exact lock inode. Read-only open avoids even
    # creating/truncating it on dry-run. /var/lock may be the native /run/lock
    # system alias; the lock FILE itself must be existing, root-owned, non-link.
    require_lock_parent
    [ -f "$LOCK" ] && [ ! -L "$LOCK" ] || die 'existing production lock is missing or unsafe'
    [ "$(stat -c '%u:%g' -- "$LOCK")" = 0:0 ] || die 'production lock is not root-owned'
    local lock_mode; lock_mode="$(stat -c '%a' -- "$LOCK")"
    (( (8#$lock_mode & 8#022) == 0 )) || die 'production lock is writable by others'
    lock_identity="$(stat -c '%d:%i' -- "$LOCK")"
    exec 9<"$LOCK"
    # Bash cannot request O_NOFOLLOW here: reject a changed/non-regular path
    # and require the opened descriptor to be the prevalidated physical inode.
    require_lock_binding "$lock_identity"
    flock -n 9 || die 'production approval/deployment lock is busy'
    require_lock_binding "$lock_identity"
    require_target
    [ "$(digest "$TARGET")" = "$OLD_SHA" ] || die 'wrapper changed while acquiring lock'
    require_live_source
    if [ "$apply" -eq 0 ]; then printf 'WRAPPER_UPGRADE=DRY_RUN\nSOURCE=%s\nOLD_SHA256=%s\nNEW_SHA256=%s\n' "$LIVE_SOURCE" "$OLD_SHA" "$NEW_SHA"; return; fi
    safe_chain "$BASE"
    if [ -e "$BACKUP_ROOT" ] || [ -L "$BACKUP_ROOT" ]; then
        safe_chain "$BACKUP_ROOT"
        [ "$(stat -c '%a' -- "$BACKUP_ROOT")" = 700 ] || die 'private backup root must be 0700'
    else
        install -d -o root -g root -m 0700 -- "$BACKUP_ROOT"
    fi
    backup="$(mktemp -d "$BACKUP_ROOT/bwork-wrapper.XXXXXXXX")"
    install -o root -g root -m 0600 -- "$TARGET" "$backup/previous-wrapper"
    [ "$(stat -c '%u:%g:%a' -- "$backup/previous-wrapper")" = 0:0:600 ] || die 'preimage backup must be root:root 0600'
    [ "$(digest "$backup/previous-wrapper")" = "$OLD_SHA" ] || die 'private preimage backup differs'
    printf 'SOURCE=%s\nOLD_SHA256=%s\nNEW_SHA256=%s\nOLD_OWNER=0:0\nOLD_MODE=0750\n' "$LIVE_SOURCE" "$OLD_SHA" "$NEW_SHA" > "$backup/metadata.env"
    chmod 0600 "$backup/metadata.env"
    sync -f -- "$backup/previous-wrapper"
    sync -f -- "$backup/metadata.env"
    sync -f -- "$backup"
    sync -f -- "$BACKUP_ROOT"
    trap 'rollback "$?"' ERR
    trap 'rollback 130' INT
    trap 'rollback 143' TERM
    trap 'rollback 129' HUP
    pending="$(mktemp "$(dirname -- "$TARGET")/.baseer-production-deploy.new.XXXXXXXX")"
    install -o root -g root -m 0750 -- "$CANDIDATE" "$pending"
    [ "$(digest "$pending")" = "$NEW_SHA" ] || die 'staged wrapper differs'
    /bin/bash -n "$pending"
    sync -f -- "$pending"
    # Set before mv: interruption after rename must restore the saved preimage.
    replacement_started=1
    mv -T -- "$pending" "$TARGET"
    pending=''
    sync -f -- "$(dirname -- "$TARGET")"
    require_target
    [ "$(digest "$TARGET")" = "$NEW_SHA" ] || die 'post-install wrapper differs'
    trap - ERR INT TERM HUP
    printf 'WRAPPER_UPGRADE=GO\nSHA256=%s\nPRIVATE_BACKUP=%s\n' "$NEW_SHA" "$backup"
}
main "$@"
