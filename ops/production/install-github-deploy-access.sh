#!/usr/bin/env bash
# Run once as root from a trusted local checkout.  The private key never enters
# this script; it accepts only the public half.
set -Eeuo pipefail

readonly DEPLOY_USER=baseer_deploy
readonly BASE=/srv/abroj-baseer-production
readonly INBOX="$BASE/deploy-inbox"
readonly STAGING="$BASE/deploy-staging"
readonly WRAPPER_DEST=/usr/local/sbin/baseer-production-deploy
readonly SUDOERS_DEST=/etc/sudoers.d/baseer-deploy
readonly SSHD_DROPIN=/etc/ssh/sshd_config.d/90-baseer-deploy.conf

[ "$(id -u)" -eq 0 ] || { echo 'root is required' >&2; exit 1; }
[ "$#" -eq 2 ] || { echo 'expected: public-key wrapper-source' >&2; exit 1; }
public_key=$1
wrapper_source=$2

case "$public_key" in
    ssh-ed25519\ *) ;;
    *) echo 'only an ed25519 public key is accepted' >&2; exit 1 ;;
esac
[ -f "$wrapper_source" ] || { echo 'wrapper source is missing' >&2; exit 1; }

id "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash --user-group "$DEPLOY_USER"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 "/home/$DEPLOY_USER/.ssh"
touch "/home/$DEPLOY_USER/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/authorized_keys"
chmod 0600 "/home/$DEPLOY_USER/.ssh/authorized_keys"
grep -Fqx "$public_key" "/home/$DEPLOY_USER/.ssh/authorized_keys" || printf '%s\n' "$public_key" >> "/home/$DEPLOY_USER/.ssh/authorized_keys"

install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0700 "$INBOX"
install -d -o root -g root -m 0700 "$STAGING"
install -o root -g root -m 0750 "$wrapper_source" "$WRAPPER_DEST"

cat > "$SUDOERS_DEST" <<'EOF'
baseer_deploy ALL=(root) NOSETENV: NOPASSWD: /usr/local/sbin/baseer-production-deploy *
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
    PermitUserEnvironment no
EOF
sshd -t
systemctl reload ssh

printf 'DEPLOY_ACCESS=READY\nUSER=%s\nINBOX=%s\nWRAPPER=%s\n' "$DEPLOY_USER" "$INBOX" "$WRAPPER_DEST"
