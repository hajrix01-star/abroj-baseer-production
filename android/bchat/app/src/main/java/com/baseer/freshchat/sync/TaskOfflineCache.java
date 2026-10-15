package com.baseer.freshchat.sync;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import org.json.JSONArray;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Bounded, read-only copies of complete task-list responses. This never queues a task write.
 * A page is scoped to the exact verified account, room, state filter and allowed-company set.
 */
public final class TaskOfflineCache extends SQLiteOpenHelper {
    public static final int PAGE_SIZE = 30;
    private static final int MAX_PAGES_PER_ACCOUNT = 4;
    private static final long MAX_BYTES_PER_ACCOUNT = 2L * 1024 * 1024;
    private static final int MAX_COMPANIES = 20;
    private static final int MAX_TASK_BYTES = 8 * 1024;
    private static final String FILE = "bchat-v2-tasks-v1.db";

    public static final class Snapshot {
        public final AccountScope account;
        public final Set<Long> companyIds;
        public final long verifiedAt;
        private Snapshot(AccountScope account, Set<Long> companyIds, long verifiedAt) {
            this.account = account;
            this.companyIds = Collections.unmodifiableSet(companyIds);
            this.verifiedAt = verifiedAt;
        }
    }

    public static final class Page {
        public final JSONArray tasks;
        public final JSONArray companies;
        public final long nextBeforeId;
        public final long verifiedAt;
        private Page(JSONArray tasks, JSONArray companies, long nextBeforeId, long verifiedAt) {
            this.tasks = tasks;
            this.companies = companies;
            this.nextBeforeId = nextBeforeId;
            this.verifiedAt = verifiedAt;
        }
    }

    public TaskOfflineCache(Context context) { super(context, FILE, null, 1); }

    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE account_scope (account_key TEXT PRIMARY KEY, origin TEXT NOT NULL, "
                + "database_name TEXT NOT NULL, user_id INTEGER NOT NULL, company_key TEXT NOT NULL, "
                + "remembered INTEGER NOT NULL, verified_at INTEGER NOT NULL)");
        db.execSQL("CREATE TABLE task_page (account_key TEXT NOT NULL, room_id INTEGER NOT NULL, "
                + "state_filter TEXT NOT NULL, company_key TEXT NOT NULL, tasks_json TEXT NOT NULL, "
                + "companies_json TEXT NOT NULL, next_before_id INTEGER NOT NULL, payload_bytes INTEGER NOT NULL, "
                + "verified_at INTEGER NOT NULL, PRIMARY KEY(account_key,room_id,state_filter,company_key))");
        db.execSQL("CREATE INDEX task_page_eviction ON task_page(account_key,verified_at)");
    }

    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        throw new IllegalStateException("Unknown BChat task cache schema");
    }

    public void save(AccountScope account, Set<Long> companyIds, long roomId, String stateFilter,
                     JSONArray tasks, JSONArray companies, long nextBeforeId, boolean remembered, long now)
            throws Exception {
        requireAccount(account);
        String companyKey = companyKey(companyIds);
        String filter = stateFilter == null ? "" : stateFilter;
        if (!(filter.isEmpty() || "new".equals(filter) || "in_progress".equals(filter)
                || "done".equals(filter) || "cancelled".equals(filter)))
            throw new IllegalArgumentException("Invalid task state filter");
        if (roomId < 0 || nextBeforeId < 0 || now <= 0 || tasks == null || companies == null
                || tasks.length() > PAGE_SIZE || companies.length() > MAX_COMPANIES)
            throw new IllegalArgumentException("Invalid verified task page");
        Set<Long> seenTasks = new HashSet<>();
        for (int index = 0; index < tasks.length(); index++) {
            String encoded = tasks.getJSONObject(index).toString();
            if (encoded.getBytes(StandardCharsets.UTF_8).length > MAX_TASK_BYTES)
                throw new IllegalArgumentException("Task is too large");
            long id = positive(tasks.getJSONObject(index).optLong("id"));
            long companyId = positive(tasks.getJSONObject(index).optLong("company_id"));
            if (!companyIds.contains(companyId) || !seenTasks.add(id))
                throw new IllegalArgumentException("Task is outside verified scope");
        }
        Set<Long> seenCompanies = new HashSet<>();
        for (int index = 0; index < companies.length(); index++) {
            long id = positive(companies.getJSONObject(index).optLong("id"));
            if (!companyIds.contains(id) || !seenCompanies.add(id))
                throw new IllegalArgumentException("Invalid verified companies");
        }
        if (!seenCompanies.equals(companyIds)) throw new IllegalArgumentException("Incomplete company scope");
        String tasksJson = tasks.toString();
        String companiesJson = companies.toString();
        long bytes = tasksJson.getBytes(StandardCharsets.UTF_8).length
                + companiesJson.getBytes(StandardCharsets.UTF_8).length;
        if (bytes <= 0 || bytes > MAX_BYTES_PER_ACCOUNT) throw new IllegalArgumentException("Task page too large");

        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            ContentValues scope = new ContentValues();
            scope.put("account_key", account.key);
            scope.put("origin", account.origin);
            scope.put("database_name", account.database);
            scope.put("user_id", account.userId);
            scope.put("company_key", companyKey);
            scope.put("remembered", remembered ? 1 : 0);
            scope.put("verified_at", now);
            db.insertWithOnConflict("account_scope", null, scope, SQLiteDatabase.CONFLICT_REPLACE);
            ContentValues page = new ContentValues();
            page.put("account_key", account.key);
            page.put("room_id", roomId);
            page.put("state_filter", filter);
            page.put("company_key", companyKey);
            page.put("tasks_json", tasksJson);
            page.put("companies_json", companiesJson);
            page.put("next_before_id", nextBeforeId);
            page.put("payload_bytes", bytes);
            page.put("verified_at", now);
            db.insertWithOnConflict("task_page", null, page, SQLiteDatabase.CONFLICT_REPLACE);
            trim(db, account.key);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    public Snapshot remembered(String origin, String database, long now, long maxAge) {
        if (now <= 0 || maxAge <= 0) return null;
        long cutoff = maxAge >= now ? 0 : now - maxAge;
        try (Cursor rows = getReadableDatabase().query("account_scope",
                new String[]{"origin", "database_name", "user_id", "company_key", "verified_at"},
                "remembered=1 AND origin=? AND database_name=? AND verified_at<=? AND verified_at>=?",
                new String[]{origin, database, String.valueOf(now), String.valueOf(cutoff)},
                null, null, "verified_at DESC", "1")) {
            if (!rows.moveToFirst()) return null;
            return new Snapshot(new AccountScope(rows.getString(0), rows.getString(1), rows.getLong(2)),
                    parseCompanyKey(rows.getString(3)), rows.getLong(4));
        }
    }

    public Page page(AccountScope account, Set<Long> companyIds, long roomId, String stateFilter) throws Exception {
        requireAccount(account);
        String filter = stateFilter == null ? "" : stateFilter;
        String companyKey = companyKey(companyIds);
        try (Cursor rows = getReadableDatabase().query("task_page",
                new String[]{"tasks_json", "companies_json", "next_before_id", "verified_at"},
                "account_key=? AND room_id=? AND state_filter=? AND company_key=?",
                new String[]{account.key, String.valueOf(roomId), filter, companyKey},
                null, null, null, "1")) {
            if (!rows.moveToFirst()) return null;
            return new Page(new JSONArray(rows.getString(0)), new JSONArray(rows.getString(1)),
                    rows.getLong(2), rows.getLong(3));
        }
    }

    /** A verified company-scope change must not leave older mixed-company task pages browsable. */
    public void purgeExceptCompanySet(AccountScope account, Set<Long> allowedCompanies) {
        requireAccount(account);
        String key = companyKey(allowedCompanies);
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            db.delete("task_page", "account_key=? AND company_key<>?", new String[]{account.key, key});
            db.update("account_scope", value("company_key", key), "account_key=?", new String[]{account.key});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    public void purgeOtherAccounts(AccountScope account) {
        requireAccount(account);
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            db.delete("task_page", "account_key<>?", new String[]{account.key});
            db.delete("account_scope", "account_key<>?", new String[]{account.key});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    public void purgeAccount(AccountScope account) {
        requireAccount(account);
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            db.delete("task_page", "account_key=?", new String[]{account.key});
            db.delete("account_scope", "account_key=?", new String[]{account.key});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    public void purgeAll() {
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            db.delete("task_page", null, null);
            db.delete("account_scope", null, null);
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }

    private static ContentValues value(String key, String value) {
        ContentValues values = new ContentValues();
        values.put(key, value);
        return values;
    }

    private static void trim(SQLiteDatabase db, String accountKey) {
        while (true) {
            long count = 0, bytes = 0;
            try (Cursor totals = db.rawQuery("SELECT COUNT(*),COALESCE(SUM(payload_bytes),0) FROM task_page WHERE account_key=?",
                    new String[]{accountKey})) {
                if (totals.moveToFirst()) { count = totals.getLong(0); bytes = totals.getLong(1); }
            }
            if (count <= MAX_PAGES_PER_ACCOUNT && bytes <= MAX_BYTES_PER_ACCOUNT) return;
            try (Cursor old = db.query("task_page", new String[]{"room_id", "state_filter", "company_key"},
                    "account_key=?", new String[]{accountKey}, null, null, "verified_at ASC", "1")) {
                if (!old.moveToFirst()) return;
                db.delete("task_page", "account_key=? AND room_id=? AND state_filter=? AND company_key=?",
                        new String[]{accountKey, String.valueOf(old.getLong(0)), old.getString(1), old.getString(2)});
            }
        }
    }

    private static String companyKey(Set<Long> companyIds) {
        if (companyIds == null || companyIds.isEmpty() || companyIds.size() > MAX_COMPANIES)
            throw new IllegalArgumentException("Verified companies required");
        List<Long> sorted = new ArrayList<>(companyIds);
        Collections.sort(sorted);
        StringBuilder value = new StringBuilder();
        for (long id : sorted) {
            positive(id);
            if (value.length() > 0) value.append(',');
            value.append(id);
        }
        return value.toString();
    }

    private static Set<Long> parseCompanyKey(String raw) {
        if (raw == null || raw.isEmpty()) throw new IllegalArgumentException("Missing company scope");
        Set<Long> ids = new HashSet<>();
        for (String value : raw.split(",", -1)) {
            long id;
            try { id = Long.parseLong(value); } catch (NumberFormatException invalid) { throw new IllegalArgumentException("Invalid company scope"); }
            if (!ids.add(positive(id)) || ids.size() > MAX_COMPANIES)
                throw new IllegalArgumentException("Invalid company scope");
        }
        return ids;
    }

    private static void requireAccount(AccountScope account) {
        if (account == null) throw new IllegalArgumentException("Verified account required");
    }

    private static long positive(long value) {
        return OutboxPolicy.requireRecordId(value);
    }
}
