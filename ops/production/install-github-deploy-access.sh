#!/usr/bin/env bash
# Run once as root from a trusted local checkout.  The private key never enters
# this script; it accepts only the public half.
set -Eeuo pipefail

readonly DEPLOY_USER=baseer_deploy
readonly BASE=/srv/abroj-baseer-production
readonly INBOX="$BASE/deploy-inbox"
readonly STAGING="$BASE/deploy-staging"
readonly WRAPPER_DEST=/usr/local/sbin/baseer-production-deploy
readonly APPROVAL_WRAPPER_DEST=/usr/local/sbin/baseer-production-approve-release
readonly SOURCE_KEY=/etc/baseer-production/source-readonly.key
readonly SOURCE_KNOWN_HOSTS=/etc/baseer-production/github-known_hosts
readonly SUDOERS_DEST=/etc/sudoers.d/baseer-deploy
readonly SSHD_DROPIN=/etc/ssh/sshd_config.d/90-baseer-deploy.conf

[ "$(id -u)" -eq 0 ] || { echo 'root is required' >&2; exit 1; }
[ "$#" -eq 3 ] || { echo 'expected: public-key deploy-wrapper-source approval-wrapper-source' >&2; exit 1; }
public_key=$1
deploy_wrapper_source=$2
approval_wrapper_source=$3

case "$public_key" in
    ssh-ed25519\ *) ;;
    *) echo 'only an ed25519 public key is accepted' >&2; exit 1 ;;
esac
[ -f "$deploy_wrapper_source" ] || { echo 'deploy wrapper source is missing' >&2; exit 1; }
[ -f "$approval_wrapper_source" ] || { echo 'approval wrapper source is missing' >&2; exit 1; }
[ -f "$SOURCE_KEY" ] && [ ! -L "$SOURCE_KEY" ] || { echo 'root-only GitHub source key is missing' >&2; exit 1; }
[ -f "$SOURCE_KNOWN_HOSTS" ] && [ ! -L "$SOURCE_KNOWN_HOSTS" ] || { echo 'GitHub known-hosts file is missing' >&2; exit 1; }
[ "$(stat -c '%U:%G:%a' "$SOURCE_KEY")" = 'root:root:600' ] || { echo 'GitHub source key ownership or mode is unsafe' >&2; exit 1; }
[ "$(stat -c '%U:%G:%a' "$SOURCE_KNOWN_HOSTS")" = 'root:root:644' ] || { echo 'GitHub known-hosts ownership or mode is unsafe' >&2; exit 1; }
grep -Fqx 'ssh.github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' "$SOURCE_KNOWN_HOSTS" || { echo 'GitHub host key is not pinned' >&2; exit 1; }
# Do not create an SSH identity or a sudo rule until the host's global SSH
# policy is proven compatible with the restricted-account contract.
sshd -t
sshd -T | grep -qx 'permituserenvironment no' || {
    echo 'PermitUserEnvironment must be globally disabled before enabling deploy access' >&2
    exit 1
}

id "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash --user-group "$DEPLOY_USER"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 "/home/$DEPLOY_USER/.ssh"
touch "/home/$DEPLOY_USER/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/authorized_keys"
chmod 0600 "/home/$DEPLOY_USER/.ssh/authorized_keys"
grep -Fqx "$public_key" "/home/$DEPLOY_USER/.ssh/authorized_keys" || printf '%s\n' "$public_key" >> "/home/$DEPLOY_USER/.ssh/authorized_keys"

install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 "$INBOX"
install -d -o root -g root -m 0700 "$STAGING"
install -o root -g root -m 0750 "$deploy_wrapper_source" "$WRAPPER_DEST"
install -o root -g root -m 0750 "$approval_wrapper_source" "$APPROVAL_WRAPPER_DEST"

cat > "$SUDOERS_DEST" <<'EOF'
baseer_deploy ALL=(root) NOSETENV: NOPASSWD: /usr/local/sbin/baseer-production-approve-release *, /usr/local/sbin/baseer-production-deploy *
EOF
chmod 0440 "$SUDOERS_DEST"
visudo -cf "$SUDOERS_DEST"

cat > "$SSHD_DROPIN" <<'EOF'
Match User baseer_deploy
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PermitTTY no
    AllowTcpForwarding no
    X11Forwarding no
    AllowAgentForwarding no
EOF
sshd -t
systemctl reload ssh

printf 'DEPLOY_ACCESS=READY\nUSER=%s\nINBOX=%s\nAPPROVAL_WRAPPER=%s\nDEPLOY_WRAPPER=%s\n' "$DEPLOY_USER" "$INBOX" "$APPROVAL_WRAPPER_DEST" "$WRAPPER_DEST"
