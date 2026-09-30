#!/usr/bin/env bash
# Installs the root-owned, pull-only QA release bridge and its timer.
set -Eeuo pipefail
umask 027

die() { printf 'QA_BOOTSTRAP=FAILED\nREASON=%s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die 'root is required'
[ "$#" -eq 6 ] || die 'expected: config approval_wrapper deploy_wrapper poller service timer'

CONFIG=$1
APPROVAL_WRAPPER=$2
DEPLOY_WRAPPER=$3
POLLER=$4
SERVICE=$5
TIMER=$6
BASE=/srv/baseer-qa

for file in "$CONFIG" "$APPROVAL_WRAPPER" "$DEPLOY_WRAPPER" "$POLLER" "$SERVICE" "$TIMER"; do
    [ -f "$file" ] && [ ! -L "$file" ] || die "missing or unsafe bootstrap file: $file"
done
[ "$(stat -c '%U:%G:%a' -- "$CONFIG")" = root:root:600 ] || die 'QA config must be root:root 600'
grep -Fqx 'QA_ENVIRONMENT=qa' "$CONFIG" || die 'QA config must declare QA_ENVIRONMENT=qa'
grep -Fqx "QA_BASE=$BASE" "$CONFIG" || die "QA config must use QA_BASE=$BASE"

install -d -o root -g root -m 0700 /etc/baseer-qa "$BASE" "$BASE/releases" "$BASE/backups" "$BASE/deploy-staging" "$BASE/processed-requests"
install -o root -g root -m 0750 "$APPROVAL_WRAPPER" /usr/local/sbin/baseer-qa-approve-release
install -o root -g root -m 0750 "$DEPLOY_WRAPPER" /usr/local/sbin/baseer-qa-deploy
install -o root -g root -m 0750 "$POLLER" /usr/local/sbin/baseer-qa-release-poller
install -o root -g root -m 0644 "$SERVICE" /etc/systemd/system/baseer-qa-release-poller.service
install -o root -g root -m 0644 "$TIMER" /etc/systemd/system/baseer-qa-release-poller.timer
systemctl daemon-reload
systemctl enable --now baseer-qa-release-poller.timer
printf 'QA_BOOTSTRAP=GO\n'
