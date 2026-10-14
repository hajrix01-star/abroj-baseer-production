#!/usr/bin/env bash
# QA-only bootstrap for the reviewed OCA path; does not restart or install Odoo.
set -Eeuo pipefail
umask 077
[ "$(id -u)" -eq 0 ] || exit 1
[ "$#" -eq 1 ] && [[ "$1" =~ ^[a-f0-9]{40}$ ]] || exit 1
revision=$1
base=/srv/baseer-qa
source_dir="$base/deploy-staging/dms-bootstrap-$revision"
[ "$(readlink -f "$source_dir")" = "$source_dir" ] || exit 1
for file in /etc/baseer-qa/deploy.env /etc/baseer-qa/compose.yaml; do
    [ -f "$file" ] && [ ! -L "$file" ] || exit 1
    [ "$(stat -c '%U:%G:%a' "$file")" = root:root:600 ] || exit 1
done
grep -Fqx 'QA_ENVIRONMENT=qa' /etc/baseer-qa/deploy.env
grep -Fqx 'QA_BASE=/srv/baseer-qa' /etc/baseer-qa/deploy.env
old_path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19
new_path="$old_path,/mnt/third-party-addons/oca_dms_19"
grep -Fq -- "--addons-path=$old_path" /etc/baseer-qa/compose.yaml
[ "$(grep -Fc -- '--addons-path=' /etc/baseer-qa/compose.yaml)" -eq 1 ]
if grep -q '^QA_ADDONS_PATH=' /etc/baseer-qa/deploy.env; then
    grep -Fqx "QA_ADDONS_PATH=$new_path" /etc/baseer-qa/deploy.env
fi
for script in baseer-qa-approve-release baseer-qa-deploy; do
    file="$source_dir/ops/qa/$script"
    [ -f "$file" ] && [ ! -L "$file" ] || exit 1
    bash -n "$file"
done
backup="$base/deploy-staging/dms-bootstrap-before-$revision"
[ ! -e "$backup" ] || exit 1
mkdir -m 0700 "$backup"
cp -a /etc/baseer-qa/deploy.env /etc/baseer-qa/compose.yaml "$backup/"
cp -a /usr/local/sbin/baseer-qa-approve-release /usr/local/sbin/baseer-qa-deploy "$backup/"
restore_bootstrap() {
    cp -a "$backup/deploy.env" /etc/baseer-qa/deploy.env
    cp -a "$backup/compose.yaml" /etc/baseer-qa/compose.yaml
    cp -a "$backup/baseer-qa-approve-release" /usr/local/sbin/baseer-qa-approve-release
    cp -a "$backup/baseer-qa-deploy" /usr/local/sbin/baseer-qa-deploy
}
trap restore_bootstrap ERR
# Exact, bounded configuration replacement; preserve all secrets/other settings.
sed -i "s@--addons-path=$old_path\$@--addons-path=$new_path@" /etc/baseer-qa/compose.yaml
if ! grep -q '^QA_ADDONS_PATH=' /etc/baseer-qa/deploy.env; then
    sed -i "\$a QA_ADDONS_PATH=$new_path" /etc/baseer-qa/deploy.env
fi
chmod 0600 /etc/baseer-qa/deploy.env /etc/baseer-qa/compose.yaml
for script in baseer-qa-approve-release baseer-qa-deploy; do
    install -o root -g root -m 0750 "$source_dir/ops/qa/$script" "/usr/local/sbin/$script"
    cmp "$source_dir/ops/qa/$script" "/usr/local/sbin/$script"
done
grep -Fqx "QA_ADDONS_PATH=$new_path" /etc/baseer-qa/deploy.env
grep -Fq -- "--addons-path=$new_path" /etc/baseer-qa/compose.yaml
trap - ERR
printf 'DMS_QA_BOOTSTRAP=GO\nBACKUP=%s\n' "$backup"
