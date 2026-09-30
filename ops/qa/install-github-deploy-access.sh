#!/usr/bin/env bash
# Run once as root on the QA host after /etc/baseer-qa/deploy.env has been
# created and reviewed locally.  This script deliberately cannot configure a
# production host: every installed name is QA-specific.
set -Eeuo pipefail
umask 027

readonly DEPLOY_USER=baseer_qa_deploy
readonly BASE=/srv/baseer-qa
readonly WRAPPER_DEST=/usr/local/sbin/baseer-qa-deploy
readonly APPROVAL_DEST=/usr/local/sbin/baseer-qa-approve-release
readonly SUDOERS_DEST=/etc/sudoers.d/baseer-qa-deploy
readonly CONFIG=/etc/baseer-qa/deploy.env

die() { printf 'QA_BOOTSTRAP=FAILED\nREASON=%s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die 'root is required'
[ "$#" -eq 3 ] || die 'expected: GitHub public key deploy-wrapper approval-wrapper'

public_key=$1
deploy_wrapper=$2
approval_wrapper=$3
[[ "$public_key" =~ ^ssh-ed25519\  ]] || die 'expected an ed25519 public key'
[ -f "$deploy_wrapper" ] && [ ! -L "$deploy_wrapper" ] || die 'deploy wrapper is missing or unsafe'
[ -f "$approval_wrapper" ] && [ ! -L "$approval_wrapper" ] || die 'approval wrapper is missing or unsafe'
[ -f "$CONFIG" ] && [ ! -L "$CONFIG" ] || die 'root-owned QA config must exist first'
[ "$(stat -c '%U:%G:%a' -- "$CONFIG")" = root:root:600 ] || die 'QA config must be root:root 600'
grep -Fqx 'QA_ENVIRONMENT=qa' "$CONFIG" || die 'QA config must declare QA_ENVIRONMENT=qa'
grep -Fqx "QA_BASE=$BASE" "$CONFIG" || die "QA config must use QA_BASE=$BASE"

if id "$DEPLOY_USER" >/dev/null 2>&1; then
    [ "$(id -gn "$DEPLOY_USER")" = "$DEPLOY_USER" ] || die 'existing deploy user has an unsafe primary group'
    [ "$(id -nG "$DEPLOY_USER")" = "$DEPLOY_USER" ] || die 'existing deploy user has unsafe supplementary groups'
else
    useradd --create-home --shell /bin/bash --user-group "$DEPLOY_USER"
fi
for group in docker sudo wheel adm admin; do
    getent group "$group" | grep -Eq "(^|:|,)$DEPLOY_USER(,|$)" && die "deploy user must not belong to $group"
done

install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 "/home/$DEPLOY_USER/.ssh"
touch "/home/$DEPLOY_USER/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/authorized_keys"
chmod 0600 "/home/$DEPLOY_USER/.ssh/authorized_keys"
grep -Fqx "$public_key" "/home/$DEPLOY_USER/.ssh/authorized_keys" || printf '%s\n' "$public_key" >> "/home/$DEPLOY_USER/.ssh/authorized_keys"

install -d -o root -g root -m 0700 /etc/baseer-qa "$BASE" "$BASE/releases" "$BASE/backups" "$BASE/deploy-staging"
install -o root -g root -m 0750 "$deploy_wrapper" "$WRAPPER_DEST"
install -o root -g root -m 0750 "$approval_wrapper" "$APPROVAL_DEST"
cat > "$SUDOERS_DEST" <<'EOF'
baseer_qa_deploy ALL=(root) NOSETENV: NOPASSWD: /usr/local/sbin/baseer-qa-approve-release *, /usr/local/sbin/baseer-qa-deploy *
EOF
chmod 0440 "$SUDOERS_DEST"
visudo -cf "$SUDOERS_DEST" >/dev/null

printf 'QA_BOOTSTRAP=READY\nUSER=%s\n' "$DEPLOY_USER"
