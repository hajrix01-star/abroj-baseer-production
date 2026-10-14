"""Disposable SQL-path capacity probe for BChat message storage.

Run only inside the isolated Odoo container, with its HOST/USER/PASSWORD env:
    python /mnt/bchat-addons/baseer_bchat/tests/capacity_chat_probe.py

This deliberately bypasses Odoo's application/API layer when seeding synthetic
rows and timing the underlying read queries. It does not certify HTTP, Android,
Bus, FCM, encryption, or end-to-end latency. The database must be empty of BChat
rooms/messages before the run. Exact fixture IDs are removed at the end.
"""

from concurrent.futures import ThreadPoolExecutor
from math import ceil
from os import environ
from statistics import median
from sys import argv
from threading import Barrier
from time import monotonic

import psycopg2


APPROVED_DB = "bchat_capacity_test_20261014"
ROOM_COUNT = 5
READER_COUNT = 10
ITERATIONS_PER_READER = 30
STAGES = (10_000, 100_000)
ROOM_PREFIX = "BChat isolated capacity 20261014 "


def connect():
    if environ.get("PGDATABASE", APPROVED_DB) != APPROVED_DB:
        raise RuntimeError("Refusing an unapproved BChat database")
    if environ.get("HOST") != "db":
        raise RuntimeError("Refusing a database host outside isolated Docker network")
    connection = psycopg2.connect(
        host="db", dbname=APPROVED_DB,
        user=environ["USER"], password=environ["PASSWORD"],
        connect_timeout=5,
        options="-c statement_timeout=30000 -c lock_timeout=5000",
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), inet_server_addr()::text")
        database, address = cursor.fetchone()
        if database != APPROVED_DB or address is None:
            connection.close()
            raise RuntimeError("Unexpected BChat capacity database")
    connection.rollback()
    return connection


def require_empty(connection):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT (SELECT count(*) FROM baseer_bchat_room),
                   (SELECT count(*) FROM baseer_bchat_message),
                   (SELECT count(*) FROM baseer_bchat_change),
                   (SELECT count(*) FROM baseer_bchat_message_receipt)
        """)
        counts = cursor.fetchone()
        if any(counts):
            raise RuntimeError("Isolated DB has existing BChat data; refusing capacity seed")
        cursor.execute("SELECT id FROM res_users WHERE login = 'admin'")
        admin = cursor.fetchone()
        cursor.execute("SELECT id FROM res_users WHERE login = '__system__'")
        system = cursor.fetchone()
        if not admin or not system:
            raise RuntimeError("Expected fresh Odoo base users are absent")
        cursor.execute("SELECT id FROM res_company WHERE id = 1")
        if not cursor.fetchone():
            raise RuntimeError("Expected fresh Odoo company is absent")
    connection.rollback()
    return admin[0], system[0]


def create_fixture(connection, admin, system):
    rooms = []
    admin_members = []
    system_members = []
    with connection.cursor() as cursor:
        for index in range(ROOM_COUNT):
            cursor.execute("""
                INSERT INTO baseer_bchat_room
                  (name, company_id, revision, invoice_policy,
                   invoice_policy_version, avatar_version, is_group,
                   create_uid, write_uid, create_date, write_date)
                VALUES (%s, 1, 0, 'off', 1, 0, TRUE, %s, %s, now(), now())
                RETURNING id
            """, (ROOM_PREFIX + str(index), admin, admin))
            room = cursor.fetchone()[0]
            rooms.append(room)
            for user, member_list in ((admin, admin_members), (system, system_members)):
                cursor.execute("""
                    INSERT INTO baseer_bchat_membership
                      (room_id, company_id, user_id, joined_after_message_id,
                       active, is_group_admin, create_uid, write_uid,
                       create_date, write_date)
                    VALUES (%s, 1, %s, 0, TRUE, FALSE, %s, %s, now(), now())
                    RETURNING id
                """, (room, user, admin, admin))
                member_list.append(cursor.fetchone()[0])
    connection.commit()
    return rooms, admin_members, system_members


def seed_to(connection, start, total, rooms, admin_members, system_members,
            admin, system):
    """Bulk insert synthetic rows; each stage commits only to disposable DB."""
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO baseer_bchat_message
              (room_id, company_id, membership_id, author_user_id, client_uuid,
               payload_digest, text, create_uid, write_uid, create_date, write_date)
            SELECT rooms[((g - 1) %% %s) + 1], 1,
                   members[((g - 1) %% %s) + 1], %s,
                   gen_random_uuid()::text, repeat('a', 64),
                   'Capacity test message ' || g || ' with bounded text.',
                   %s, %s, now(), now()
            FROM generate_series(%s, %s) AS g,
                 (SELECT %s::integer[] AS rooms, %s::integer[] AS members) AS fixture
        """, (ROOM_COUNT, ROOM_COUNT, system, admin, admin, start + 1, total,
              rooms, system_members))
        if cursor.rowcount != total - start:
            raise RuntimeError("Synthetic message count mismatch")
        cursor.execute("""
            INSERT INTO baseer_bchat_message_receipt
              (message_id, membership_id, recipient_user_id, company_id,
               create_uid, write_uid, create_date, write_date)
            SELECT message.id,
                   members[(array_position(rooms, message.room_id))], %s, 1,
                   %s, %s, now(), now()
            FROM baseer_bchat_message AS message,
                 (SELECT %s::integer[] AS rooms, %s::integer[] AS members) AS fixture
            WHERE message.room_id = ANY(rooms)
              AND message.id > %s
            ORDER BY message.id
        """, (admin, admin, admin, rooms, admin_members,
              _last_message_id(cursor, rooms, start)))
        if cursor.rowcount != total - start:
            raise RuntimeError("Synthetic receipt count mismatch")
        cursor.execute("""
            INSERT INTO baseer_bchat_change
              (user_id, sequence, kind, room_id, membership_id, message_id,
               company_id, create_uid, write_uid, create_date, write_date)
            SELECT %s, row_number() OVER (ORDER BY message.id) + %s,
                   'message', message.room_id,
                   members[array_position(rooms, message.room_id)],
                   message.id, 1, %s, %s, now(), now()
            FROM baseer_bchat_message AS message,
                 (SELECT %s::integer[] AS rooms, %s::integer[] AS members) AS fixture
            WHERE message.room_id = ANY(rooms)
              AND message.id > %s
            ORDER BY message.id
        """, (admin, start, admin, admin, rooms, admin_members,
              _last_message_id(cursor, rooms, start)))
        if cursor.rowcount != total - start:
            raise RuntimeError("Synthetic change count mismatch")
        cursor.execute("""
            INSERT INTO baseer_bchat_change_cursor
              (user_id, sequence, create_uid, write_uid, create_date, write_date)
            VALUES (%s, %s, %s, %s, now(), now())
            ON CONFLICT (user_id) DO UPDATE SET sequence = EXCLUDED.sequence,
                 write_uid = EXCLUDED.write_uid, write_date = now()
        """, (admin, total, admin, admin))
    connection.commit()
    with connection.cursor() as cursor:
        for table in ("baseer_bchat_message", "baseer_bchat_message_receipt",
                      "baseer_bchat_change"):
            cursor.execute("ANALYZE " + table)
    connection.commit()


def _last_message_id(cursor, rooms, start):
    if start == 0:
        return 0
    cursor.execute("""
        SELECT id FROM baseer_bchat_message
        WHERE room_id = ANY(%s) ORDER BY id ASC OFFSET %s LIMIT 1
    """, (rooms, start - 1))
    row = cursor.fetchone()
    if not row:
        raise RuntimeError("Prior stage boundary was lost")
    return row[0]


HISTORY = """
    SELECT id, room_id, author_user_id, text, create_date
    FROM baseer_bchat_message
    WHERE room_id = %s AND id > 0 AND id < %s
    ORDER BY id DESC LIMIT 31
"""

ROOMS = """
    SELECT membership.id, latest.id, latest.text, latest.create_date,
           COALESCE(unread.total, 0), COALESCE(members.total, 0)
    FROM baseer_bchat_membership AS membership
    LEFT JOIN LATERAL (
        SELECT message.id, message.text, message.create_date
        FROM baseer_bchat_message AS message
        WHERE message.room_id = membership.room_id
          AND message.id > membership.joined_after_message_id
        ORDER BY message.id DESC LIMIT 1
    ) AS latest ON TRUE
    LEFT JOIN LATERAL (
        SELECT COUNT(*) AS total
        FROM baseer_bchat_message_receipt AS receipt
        JOIN baseer_bchat_message AS message ON message.id = receipt.message_id
        WHERE receipt.membership_id = membership.id
          AND receipt.recipient_user_id = %s
          AND receipt.read_at IS NULL
          AND message.room_id = membership.room_id
          AND message.id > membership.joined_after_message_id
    ) AS unread ON TRUE
    LEFT JOIN LATERAL (
        SELECT COUNT(*) AS total FROM baseer_bchat_membership AS other
        WHERE other.room_id = membership.room_id AND other.active
    ) AS members ON TRUE
    WHERE membership.id = ANY(%s) AND membership.active
"""

FEED = """
    SELECT id, sequence, kind, room_id, membership_id, message_id
    FROM baseer_bchat_change
    WHERE user_id = %s AND sequence > %s AND sequence <= %s
    ORDER BY sequence LIMIT 101
"""

# Diagnostic alternative only. The service writer creates a receipt for the
# same room and membership epoch as its message, but there is no DB constraint
# enforcing that cross-table fact. Do not ship this rewrite without G2 review.
ROOMS_UNREAD_DIRECT = ROOMS.replace(
    """        JOIN baseer_bchat_message AS message ON message.id = receipt.message_id
        WHERE receipt.membership_id = membership.id
          AND receipt.recipient_user_id = %s
          AND receipt.read_at IS NULL
          AND message.room_id = membership.room_id
          AND message.id > membership.joined_after_message_id
""",
    """        WHERE receipt.membership_id = membership.id
          AND receipt.recipient_user_id = %s
          AND receipt.read_at IS NULL
          AND receipt.message_id > membership.joined_after_message_id
""",
)


def percentile(values, ratio):
    ordered = sorted(values)
    return round(ordered[max(0, ceil(len(ordered) * ratio) - 1)], 2)


def measure(total, rooms, admin_members, admin):
    barrier = Barrier(READER_COUNT)
    samples = {"history": [], "rooms": [], "feed": []}
    errors = []
    boundaries = {}
    prepared = connect()
    try:
        with prepared.cursor() as cursor:
            for room in rooms:
                for position in range(3):
                    page = position * (total // ROOM_COUNT // 3)
                    cursor.execute("""
                        SELECT id FROM baseer_bchat_message
                        WHERE room_id = %s ORDER BY id DESC OFFSET %s LIMIT 1
                    """, (room, page))
                    row = cursor.fetchone()
                    boundaries[(room, position)] = row[0] + 1 if row else 2147483647
    finally:
        prepared.close()

    def reader(index):
        local = {key: [] for key in samples}
        connection = connect()
        connection.autocommit = True
        try:
            barrier.wait(timeout=20)
            with connection.cursor() as cursor:
                for iteration in range(ITERATIONS_PER_READER):
                    room = rooms[(index + iteration) % ROOM_COUNT]
                    # Exercise latest, middle, and old keyset pages, not OFFSET pagination.
                    before_id = boundaries[(room, iteration % 3)]
                    after = max(0, total - (iteration % 3) * (total // 3) - 100)
                    for name, sql, args in (
                        ("history", HISTORY, (room, before_id)),
                        ("rooms", ROOMS, (admin, admin_members)),
                        ("feed", FEED, (admin, after, total)),
                    ):
                        started = monotonic()
                        cursor.execute(sql, args)
                        rows = cursor.fetchall()
                        local[name].append((monotonic() - started) * 1000)
                        if name == "history" and not 1 <= len(rows) <= 31:
                            raise AssertionError("Unexpected history page")
                        if name == "rooms" and len(rows) != ROOM_COUNT:
                            raise AssertionError("Unexpected room list")
                        if name == "feed" and not 1 <= len(rows) <= 101:
                            raise AssertionError("Unexpected feed page")
        finally:
            connection.close()
        return local

    with ThreadPoolExecutor(max_workers=READER_COUNT) as pool:
        futures = [pool.submit(reader, index) for index in range(READER_COUNT)]
        for future in futures:
            try:
                local = future.result(timeout=120)
            except Exception as error:
                errors.append(type(error).__name__ + ": " + str(error))
            else:
                for name in samples:
                    samples[name].extend(local[name])
    return {
        "messages": total, "readers": READER_COUNT,
        "samples_per_query": READER_COUNT * ITERATIONS_PER_READER,
        "error_count": len(errors), "errors": errors[:3],
        "queries": {
            name: {"samples": len(values), "p50_ms": round(median(values), 2),
                   "p95_ms": percentile(values, .95),
                   "p99_ms": percentile(values, .99),
                   "max_ms": round(max(values), 2)}
            for name, values in samples.items() if values
        },
        "scope": "isolated PostgreSQL read queries; not Odoo HTTP or device E2E",
    }


def cleanup(connection, rooms, admin):
    if not rooms:
        return
    with connection.cursor() as cursor:
        cursor.execute("SET statement_timeout = '5min'")
        cursor.execute("SELECT count(*) FROM baseer_bchat_room WHERE id = ANY(%s) AND name LIKE %s",
                       (rooms, ROOM_PREFIX + "%"))
        if cursor.fetchone()[0] != ROOM_COUNT:
            raise RuntimeError("Fixture room identity changed; refusing broad deletion")
        cursor.execute("SELECT count(*) FROM baseer_bchat_room")
        if cursor.fetchone()[0] != ROOM_COUNT:
            raise RuntimeError("Unrelated BChat rooms appeared; refusing cleanup")
        cursor.execute("DELETE FROM baseer_bchat_change WHERE room_id = ANY(%s)", (rooms,))
    connection.commit()
    with connection.cursor() as cursor:
        cursor.execute("SET statement_timeout = '5min'")
        cursor.execute("""
            DELETE FROM baseer_bchat_message_receipt
            WHERE message_id IN (SELECT id FROM baseer_bchat_message WHERE room_id = ANY(%s))
        """, (rooms,))
    connection.commit()
    with connection.cursor() as cursor:
        cursor.execute("SET statement_timeout = '5min'")
        cursor.execute("DELETE FROM baseer_bchat_message WHERE room_id = ANY(%s)", (rooms,))
        cursor.execute("DELETE FROM baseer_bchat_membership WHERE room_id = ANY(%s)", (rooms,))
        cursor.execute("DELETE FROM baseer_bchat_room WHERE id = ANY(%s)", (rooms,))
        cursor.execute("DELETE FROM baseer_bchat_change_cursor WHERE user_id = %s", (admin,))
    connection.commit()


def cleanup_only():
    connection = connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM res_users WHERE login = 'admin'")
            admin = cursor.fetchone()[0]
            cursor.execute("SELECT id FROM baseer_bchat_room WHERE name LIKE %s ORDER BY id",
                           (ROOM_PREFIX + "%",))
            rooms = [row[0] for row in cursor.fetchall()]
            if len(rooms) != ROOM_COUNT:
                raise RuntimeError("Expected exactly five isolated capacity fixture rooms")
        connection.rollback()
        cleanup(connection, rooms, admin)
    finally:
        connection.close()


def diagnose_rooms():
    """One targeted 100k fixture for the room-list unread-count query plan."""
    connection = connect()
    rooms = []
    admin = None
    try:
        admin, system = require_empty(connection)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_database_size(current_database())")
            initial_size = cursor.fetchone()[0]
        connection.rollback()
        rooms, admin_members, system_members = create_fixture(connection, admin, system)
        started = monotonic()
        seed_to(connection, 0, 100_000, rooms, admin_members,
                system_members, admin, system)
        seed_seconds = round(monotonic() - started, 2)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_database_size(current_database())")
            seeded_size = cursor.fetchone()[0]
            cursor.execute("EXPLAIN (ANALYZE, BUFFERS) " + ROOMS,
                           (admin, admin_members))
            plan = '\n'.join(row[0] for row in cursor.fetchall())
            cursor.execute("EXPLAIN (ANALYZE, BUFFERS) " + ROOMS_UNREAD_DIRECT,
                           (admin, admin_members))
            direct_plan = '\n'.join(row[0] for row in cursor.fetchall())
            cursor.execute(ROOMS, (admin, admin_members))
            original_counts = [row[4] for row in cursor.fetchall()]
            cursor.execute(ROOMS_UNREAD_DIRECT, (admin, admin_members))
            direct_counts = [row[4] for row in cursor.fetchall()]
            if original_counts != direct_counts:
                raise AssertionError("Direct unread count changed test fixture results")
        connection.rollback()
        print({"messages": 100_000, "seed_seconds": seed_seconds,
               "db_size_before_bytes": initial_size,
               "db_size_seeded_bytes": seeded_size,
               "db_growth_bytes": seeded_size - initial_size}, flush=True)
        print("ORIGINAL QUERY PLAN\n" + plan, flush=True)
        print("DIRECT RECEIPT COUNT QUERY PLAN\n" + direct_plan, flush=True)
    finally:
        if rooms and admin:
            connection.rollback()
            cleanup(connection, rooms, admin)
        connection.close()


def run():
    connection = connect()
    rooms = []
    admin = None
    try:
        admin, system = require_empty(connection)
        rooms, admin_members, system_members = create_fixture(connection, admin, system)
        for previous, stage in zip((0,) + STAGES[:-1], STAGES):
            started = monotonic()
            seed_to(connection, previous, stage, rooms, admin_members,
                    system_members, admin, system)
            result = measure(stage, rooms, admin_members, admin)
            result["stage_seconds"] = round(monotonic() - started, 2)
            print(result, flush=True)
            if result["error_count"]:
                raise RuntimeError("Capacity readers reported errors")
    finally:
        if rooms and admin:
            connection.rollback()
            cleanup(connection, rooms, admin)
        connection.close()


if __name__ == "__main__":
    if len(argv) == 2 and argv[1] == "--cleanup":
        cleanup_only()
    elif len(argv) == 2 and argv[1] == "--diagnose-rooms":
        diagnose_rooms()
    elif len(argv) == 1:
        run()
    else:
        raise SystemExit("Usage: capacity_chat_probe.py [--cleanup|--diagnose-rooms]")
