package com.baseer.freshchat.sync;

import java.net.URI;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;

/** Non-secret identity from a verified session bootstrap, never a user-chosen company label. */
public final class AccountScope {
    public final String origin;
    public final String database;
    public final long userId;
    public final String key;

    public AccountScope(String origin, String database, long userId) {
        if (origin == null || database == null || database.trim().isEmpty() || database.length() > 128 ||
                database.indexOf('\n') >= 0 || database.indexOf('\r') >= 0 || userId <= 0 || userId > OutboxPolicy.MAX_RECORD_ID) {
            throw new IllegalArgumentException("Verified origin, database and user are required");
        }
        try {
            URI uri = new URI(origin);
            if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null ||
                    uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null ||
                    !(uri.getPath().isEmpty() || "/".equals(uri.getPath())) ||
                    uri.getPort() == 0 || uri.getPort() > 65535) {
                throw new IllegalArgumentException("An HTTPS origin without credentials or a path is required");
            }
            int port = uri.getPort();
            this.origin = "https://" + uri.getHost().toLowerCase(Locale.ROOT) +
                    ((port == -1 || port == 443) ? "" : ":" + port);
        } catch (URISyntaxException error) {
            throw new IllegalArgumentException("Invalid server origin");
        }
        this.database = database;
        this.userId = userId;
        this.key = sha256(this.origin + "\n" + database + "\n" + userId);
    }

    static String sha256(String value) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder out = new StringBuilder(64);
            for (byte b : bytes) out.append(String.format(Locale.ROOT, "%02x", b & 0xff));
            return out.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
}
