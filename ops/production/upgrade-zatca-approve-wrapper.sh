#!/bin/bash
# One-purpose control-plane replacement for the policy approver.  It is never
# a release tool: it cannot install addons, write policies, or restart Odoo.
set -Eeuo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C
umask 077

readonly BASE=/srv/abroj-baseer-production
readonly CURRENT="$BASE/current"
readonly TARGET=/usr/local/sbin/baseer-production-approve-release
readonly LOCK=/var/lock/baseer-production-deploy.lock
readonly BACKUP_ROOT="$BASE/control-plane-backups"
readonly OLD_SHA=bd211f576dfeabb8a844c0dd7a5b0cadaa5472af21f94b41c9ff5856be2a5053
readonly NEW_SHA=1b3cfbb6f714ba85162dd500fbddd7e5255cecbc01463014116a1c70690d35a1
readonly LIVE_SOURCE=b071cf811fe2525cda7e6f71c030d712aafa0a57
readonly SCRIPT_DIR="$(dirname -- "$(realpath -m -s -- "${BASH_SOURCE[0]}")")"
readonly CANDIDATE="$SCRIPT_DIR/baseer-production-approve-release"
started=0 backup='' pending=''

digest() { sha256sum -- "$1" | cut -d ' ' -f 1; }
die() { printf 'APPROVER_UPGRADE=FAILED\nREASON=%s\n' "$1" >&2; rollback 1; }
safe_chain() { local p=$1 m; while :; do [ -d "$p" ] && [ ! -L "$p" ] || die 'unsafe directory'; [ "$(stat -c '%u:%g' -- "$p")" = 0:0 ] || die 'directory is not root-owned'; m="$(stat -c '%a' -- "$p")"; (( (8#$m & 8#022) == 0 )) || die 'directory is writable by others'; [ "$p" = / ] && break; p="$(dirname -- "$p")"; done; }
safe_file() { local m; [ -f "$1" ] && [ ! -L "$1" ] || die 'unsafe regular file'; safe_chain "$(dirname -- "$1")"; [ "$(stat -c '%u:%g' -- "$1")" = 0:0 ] || die 'file is not root-owned'; m="$(stat -c '%a' -- "$1")"; (( (8#$m & 8#022) == 0 )) || die 'file is writable by others'; }
rollback() { local status=$1 restore; [ "$started" -eq 1 ] || exit "$status"; restore="$(mktemp "$(dirname -- "$TARGET")/.baseer-production-approve-release.rollback.XXXXXXXX")"; if install -o root -g root -m 0750 -- "$backup/previous-wrapper" "$restore" && [ "$(digest "$restore")" = "$OLD_SHA" ]; then mv -T -- "$restore" "$TARGET"; sync -f -- "$(dirname -- "$TARGET")"; printf 'APPROVER_ROLLBACK=GO\n' >&2; else printf 'APPROVER_ROLLBACK=FAILED\n' >&2; fi; exit "$status"; }

main() {
  local apply=0 current release lock_id
  [ "$(id -u)" -eq 0 ] || die 'root is required'
  case "$#:$*" in 0:|1:--dry-run) ;; 1:--apply) apply=1 ;; *) die 'expected --dry-run or --apply' ;; esac
  safe_file "$TARGET"; [ "$(stat -c '%u:%g:%a' -- "$TARGET")" = 0:0:750 ] || die 'target mode is unsafe'
  current="$(digest "$TARGET")"; [ "$current" = "$NEW_SHA" ] && { printf 'APPROVER_UPGRADE=ALREADY_CURRENT\n'; return; }; [ "$current" = "$OLD_SHA" ] || die 'unexpected installed approver hash'
  safe_file "$CANDIDATE"; [ "$(digest "$CANDIDATE")" = "$NEW_SHA" ] || die 'candidate is not the exact reviewed raw Git blob'; /bin/bash -n "$CANDIDATE"
  release="$(readlink -f -- "$CURRENT")"; [[ "$release" == "$BASE/releases/"* ]] || die 'current release escaped root'; safe_chain "$release"; safe_file "$release/RELEASE_COMMIT"; [ "$(cat -- "$release/RELEASE_COMMIT")" = "$LIVE_SOURCE" ] || die 'current source is not the reviewed baseline'
  [ -f "$LOCK" ] && [ ! -L "$LOCK" ] && [ "$(stat -c '%u:%g' -- "$LOCK")" = 0:0 ] || die 'production lock is unsafe'; lock_id="$(stat -c '%d:%i' -- "$LOCK")"; exec 9<"$LOCK"; flock -n 9 || die 'production lock is busy'; [ "$(stat -c '%d:%i' -- /proc/self/fd/9)" = "$lock_id" ] || die 'production lock changed'
  [ "$apply" -eq 1 ] || { printf 'APPROVER_UPGRADE=DRY_RUN\nSOURCE=%s\nOLD_SHA256=%s\nNEW_SHA256=%s\n' "$LIVE_SOURCE" "$OLD_SHA" "$NEW_SHA"; return; }
  if [ -e "$BACKUP_ROOT" ]; then safe_chain "$BACKUP_ROOT"; [ "$(stat -c '%a' -- "$BACKUP_ROOT")" = 700 ] || die 'backup root mode is unsafe'; else install -d -o root -g root -m 0700 "$BACKUP_ROOT"; fi
  backup="$(mktemp -d "$BACKUP_ROOT/zatca-approve-wrapper.XXXXXXXX")"; install -o root -g root -m 0600 -- "$TARGET" "$backup/previous-wrapper"; [ "$(digest "$backup/previous-wrapper")" = "$OLD_SHA" ] || die 'backup differs'
  trap 'rollback "$?"' ERR INT TERM HUP
  pending="$(mktemp "$(dirname -- "$TARGET")/.baseer-production-approve-release.new.XXXXXXXX")"; install -o root -g root -m 0750 -- "$CANDIDATE" "$pending"; [ "$(digest "$pending")" = "$NEW_SHA" ] || die 'staged approver differs'; started=1; mv -T -- "$pending" "$TARGET"; pending=''; sync -f -- "$(dirname -- "$TARGET")"; [ "$(digest "$TARGET")" = "$NEW_SHA" ] || die 'post-install differs'; trap - ERR INT TERM HUP; started=0; printf 'APPROVER_UPGRADE=GO\nSHA256=%s\nPRIVATE_BACKUP=%s\n' "$NEW_SHA" "$backup"
}
main "$@"
