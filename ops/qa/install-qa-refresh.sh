#!/usr/bin/env bash
# One-time bounded root bootstrap; does not operate any Docker resource.
set -Eeuo pipefail
umask 077
[ "$(id -u)" -eq 0 ]
[ "$#" -eq 1 ] && [[ "$1" =~ ^[a-f0-9]{40}$ ]]
revision=$1
source_dir="/srv/baseer-qa/deploy-staging/qa-refresh-bootstrap-$revision"
[ "$(readlink -f "$source_dir")" = "$source_dir" ]
[ "$(stat -c '%U:%G:%a' "$source_dir")" = root:root:700 ]
repo="$source_dir/repo.git"
git -C "$repo" cat-file -e "$revision^{commit}"
git -C "$repo" merge-base --is-ancestor "$revision" refs/heads/reviewed-main
for script in ops/qa/install-qa-refresh.sh ops/qa/baseer-qa-refresh ops/qa/refresh-qa.py ops/qa/verify-qa-refresh-odoo.py; do
    [ -f "$source_dir/$script" ] && [ ! -L "$source_dir/$script" ]
    git -C "$repo" show "$revision:$script" > "$source_dir/expected"
    cmp "$source_dir/expected" "$source_dir/$script"
done
bash -n "$source_dir/ops/qa/baseer-qa-refresh"
python3 - "$source_dir/ops/qa/refresh-qa.py" <<'PY'
import ast, pathlib, sys
ast.parse(pathlib.Path(sys.argv[1]).read_text())
PY
backup="$source_dir/before-install"
[ ! -e "$backup" ]
mkdir -m 0700 "$backup"
for installed in /usr/local/sbin/baseer-qa-refresh /usr/local/lib/baseer-qa-refresh/refresh-qa.py /usr/local/lib/baseer-qa-refresh/verify-qa-refresh-odoo.py; do
    if [ -e "$installed" ]; then
        [ -f "$installed" ] && [ ! -L "$installed" ]
        cp -a --parents "$installed" "$backup/"
    fi
done
install -d -o root -g root -m 0750 /usr/local/lib/baseer-qa-refresh
install -o root -g root -m 0750 "$source_dir/ops/qa/refresh-qa.py" /usr/local/lib/baseer-qa-refresh/refresh-qa.py
install -o root -g root -m 0750 "$source_dir/ops/qa/verify-qa-refresh-odoo.py" /usr/local/lib/baseer-qa-refresh/verify-qa-refresh-odoo.py
install -o root -g root -m 0750 "$source_dir/ops/qa/baseer-qa-refresh" /usr/local/sbin/baseer-qa-refresh
cmp "$source_dir/ops/qa/refresh-qa.py" /usr/local/lib/baseer-qa-refresh/refresh-qa.py
cmp "$source_dir/ops/qa/verify-qa-refresh-odoo.py" /usr/local/lib/baseer-qa-refresh/verify-qa-refresh-odoo.py
cmp "$source_dir/ops/qa/baseer-qa-refresh" /usr/local/sbin/baseer-qa-refresh
printf 'QA_REFRESH_BOOTSTRAP=PASS\nREVISION=%s\n' "$revision"
