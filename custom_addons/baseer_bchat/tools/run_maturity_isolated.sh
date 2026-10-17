#!/usr/bin/env bash
# Run only a frozen CI archive: synthetic PostgreSQL, no published ports or secrets.
set -Eeuo pipefail
ROOT="$(pwd -P)"
case "$ROOT" in /tmp/bchat-maturity-20261017-*) ;; *) echo 'Refusing non-test root' >&2; exit 2;; esac
test -f "$ROOT/custom_addons/baseer_bchat/__manifest__.py"
[[ "${BCHAT_SOURCE_COMMIT:-}" =~ ^[0-9a-f]{40}$ ]] || { echo 'Frozen commit required' >&2; exit 2; }
ODOO='odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd'
PG='postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94'
suffix="${ROOT##*/}"
db="${suffix}-db"
runner="${suffix}-orm"
probe="${suffix}-probes"
docker image inspect "$ODOO" >/dev/null
docker image inspect "$PG" >/dev/null
for name in "$db" "$runner" "$probe"; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo 'Test container already exists; inspect it, never overwrite.' >&2; exit 2
    fi
done
# Preserve source/logs/stopped containers for the job; never touch another container.
stop_ours() {
    result=$?
    if [ "$result" -ne 0 ]; then
        # Metadata only: no SQL text, payload, user names or token/config data.
        timeout --kill-after=2s 5s docker exec "$db" psql -h 127.0.0.1 -p 5432 \
            -U bchat_test -d bchat_maturity_test_20261017 -A -F , -t -c \
            "SELECT pid,state,wait_event_type,wait_event,pg_blocking_pids(pid),EXTRACT(EPOCH FROM (clock_timestamp()-query_start))::integer FROM pg_stat_activity WHERE datname='bchat_maturity_test_20261017' AND pid<>pg_backend_pid()" \
            > "$ROOT/failure-db-state.log" 2>&1 || true
        timeout --kill-after=2s 5s docker inspect --format '{{.State.OOMKilled}} {{.State.ExitCode}}' "$runner" \
            > "$ROOT/failure-runtime-state.log" 2>&1 || true
    fi
    for name in "$probe" "$runner" "$db"; do
        timeout --kill-after=2s 8s docker stop --time 5 "$name" >/dev/null 2>&1 || true
    done
}
trap stop_ours EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'SOURCE_COMMIT=%s\nTEST_ROOT=%s\nODOO_IMAGE=%s\nPG_IMAGE=%s\n' "$BCHAT_SOURCE_COMMIT" "$ROOT" "$ODOO" "$PG" | tee "$ROOT/provenance.log"
find custom_addons/baseer_bchat -type f -print0 | sort -z | xargs -0 sha256sum > "$ROOT/source.sha256"
docker run --detach --name "$db" --network none --memory 512m --cpus .5 --pids-limit 128 \
    --security-opt no-new-privileges --tmpfs /var/lib/postgresql/data:rw,nosuid,size=384m \
    -e PGDATA=/var/lib/postgresql/data/pgdata -e POSTGRES_USER=bchat_test \
    -e POSTGRES_DB=postgres -e POSTGRES_HOST_AUTH_METHOD=trust "$PG" \
    -c statement_timeout=45000 -c lock_timeout=10000 >/dev/null
ready=0
for n in {1..30}; do
    if docker exec "$db" pg_isready -h 127.0.0.1 -p 5432 -U bchat_test -d postgres >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
done
test "$ready" = 1
# Trust auth and the test HTTP server are loopback-only inside the isolated PG
# namespace. No cron, operational database, host network, filestore or FCM access.
common=(--network "container:$db" --read-only --memory 2048m --cpus 2 --pids-limit 256
    --security-opt no-new-privileges -e PYTHONDONTWRITEBYTECODE=1
    -e ODOO_TEST_MAX_FAILED_TESTS=5
    --tmpfs /tmp:rw,nosuid,size=128m --tmpfs /var/lib/odoo:rw,uid=100,gid=101,size=256m
    --mount "type=bind,src=$ROOT/custom_addons/baseer_bchat,dst=/mnt/maturity/baseer_bchat,readonly"
    --entrypoint /usr/bin/odoo)
options=(--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/maturity
    --db_host=127.0.0.1 --db_port=5432 --db_user=bchat_test --db_password=
    --database=bchat_maturity_test_20261017 --db-filter='^bchat_maturity_test_20261017$'
    --no-database-list --workers=0 --max-cron-threads=0 --without-demo=all)
set +e
timeout --kill-after=15s --signal=TERM 16m docker run --name "$runner" "${common[@]}" "$ODOO" "${options[@]}" \
    --http-interface=127.0.0.1 --http-port=8069 --init=hr,baseer_bchat \
    --test-enable --test-tags=/baseer_bchat --stop-after-init --log-level=test \
    2>&1 | tee "$ROOT/orm.log"
result=${PIPESTATUS[0]}
set -e
printf 'ORM_PROCESS_EXIT=%s\n' "$result"
test "$result" = 0
# These probes commit synthetic fixtures and MUST be invoked explicitly; Odoo
# discovery intentionally does not import them as TransactionCase tests.
set +e
timeout --kill-after=15s --signal=TERM 4m docker run --interactive --name "$probe" "${common[@]}" "$ODOO" shell \
    "${options[@]}" --no-http --log-level=info \
    < "$ROOT/custom_addons/baseer_bchat/tools/run_maturity_probes.py" 2>&1 | tee "$ROOT/probes.log"
result=${PIPESTATUS[0]}
set -e
printf 'PROBE_PROCESS_EXIT=%s\n' "$result"
test "$result" = 0
sha256sum --check "$ROOT/source.sha256" > "$ROOT/source-check.log"
python3 "$ROOT/custom_addons/baseer_bchat/tools/check_maturity_evidence.py" \
    --root "$ROOT/custom_addons/baseer_bchat" --orm-log "$ROOT/orm.log" --probe-log "$ROOT/probes.log" \
    --source-commit "$BCHAT_SOURCE_COMMIT" --output "$ROOT/evidence.json"
