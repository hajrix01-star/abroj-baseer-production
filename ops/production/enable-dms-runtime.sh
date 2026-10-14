#!/usr/bin/env bash
# Protected production workflow bootstrap: reviewed wrappers only. This never
# changes a release, Compose, Odoo configuration, database, or running service.
set -Eeuo pipefail
umask 077
[ "$(id -u)" -eq 0 ] || exit 1
[ "$#" -eq 2 ] && [[ "$1" =~ ^[a-f0-9]{40}$ ]] && [[ "$2" =~ ^[0-9]+$ ]] || exit 1
revision=$1
run_id=$2
base=/srv/abroj-baseer-production
source_dir="$base/deploy-staging/dms-bootstrap-$revision"
[ "$(readlink -f "$source_dir")" = "$source_dir" ] || exit 1
[ "$(stat -c '%U:%G:%a' "$source_dir")" = root:root:700 ] || exit 1
[ -f "$source_dir/REVIEWED_SOURCE_COMMIT" ] && [ ! -L "$source_dir/REVIEWED_SOURCE_COMMIT" ] || exit 1
[ "$(tr -d '\r\n' < "$source_dir/REVIEWED_SOURCE_COMMIT")" = "$revision" ] || exit 1
exec 9>/var/lock/baseer-production-deploy.lock
flock -n 9 || exit 1
source_key=/etc/baseer-production/source-readonly.key
known_hosts=/etc/baseer-production/github-known_hosts
for file in "$source_key" "$known_hosts"; do
    [ -f "$file" ] && [ ! -L "$file" ] || exit 1
done
[ "$(stat -c '%U:%G:%a' "$source_key")" = root:root:600 ] || exit 1
[ "$(stat -c '%U:%G:%a' "$known_hosts")" = root:root:644 ] || exit 1
grep -Fqx '[ssh.github.com]:443 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' "$known_hosts"
fetch_repo="$base/deploy-staging/dms-bootstrap-verify-$revision-$run_id.git"
[ ! -e "$fetch_repo" ] || exit 1
trap 'rm -rf -- "$fetch_repo"' EXIT
git init --bare --quiet "$fetch_repo"
git -C "$fetch_repo" remote add origin ssh://git@ssh.github.com:443/hajrix01-star/abroj-baseer-production.git
GIT_SSH_COMMAND="ssh -i $source_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$known_hosts" \
    git -C "$fetch_repo" fetch --no-tags --quiet origin main:refs/heads/reviewed-main "$revision"
git -C "$fetch_repo" cat-file -e "$revision^{commit}"
git -C "$fetch_repo" merge-base --is-ancestor "$revision" refs/heads/reviewed-main
for script in baseer-production-approve-release baseer-production-deploy; do
    file="$source_dir/ops/production/$script"
    [ -f "$file" ] && [ ! -L "$file" ] || exit 1
    [ "$(stat -c '%U:%G' "$file")" = root:root ] || exit 1
    [ "$(git -C "$fetch_repo" ls-tree "$revision" -- "ops/production/$script" | awk '{print $1}')" = 100644 ] || exit 1
    reviewed_hash="$(git -C "$fetch_repo" show "$revision:ops/production/$script" | sha256sum | awk '{print $1}')"
    [ "$(sha256sum "$file" | awk '{print $1}')" = "$reviewed_hash" ] || exit 1
    bash -n "$file"
    [ -f "/usr/local/sbin/$script" ] && [ ! -L "/usr/local/sbin/$script" ] || exit 1
done
backup="$base/deploy-staging/dms-bootstrap-before-$revision-$run_id"
[ ! -e "$backup" ] || exit 1
mkdir -m 0700 "$backup"
for script in baseer-production-approve-release baseer-production-deploy; do
    cp -a "/usr/local/sbin/$script" "$backup/"
done
restore_wrappers() {
    trap - ERR
    for script in baseer-production-approve-release baseer-production-deploy; do
        cp -a "$backup/$script" "/usr/local/sbin/$script"
        cmp "$backup/$script" "/usr/local/sbin/$script"
    done
}
trap restore_wrappers ERR
for script in baseer-production-approve-release baseer-production-deploy; do
    install -o root -g root -m 0750 "$source_dir/ops/production/$script" "/usr/local/sbin/$script"
    cmp "$source_dir/ops/production/$script" "/usr/local/sbin/$script"
done
trap - ERR
printf 'DMS_PRODUCTION_BOOTSTRAP=GO\nSOURCE_COMMIT=%s\nRUN_ID=%s\nBACKUP=%s\n' "$revision" "$run_id" "$backup"
