package com.baseer.freshchat;

import javax.net.ssl.HttpsURLConnection;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Native, capability-scoped media transport.  It deliberately has no CookieManager access and
 * never logs capability material or file bytes.  Callers run it off the UI thread.
 */
final class BChatNativeMediaUploader {
    private static final int CONNECT_TIMEOUT_MS = 15_000;
    private static final int READ_TIMEOUT_MS = 90_000;
    private static final int RESPONSE_LIMIT = 8 * 1024;
    private static final int BUFFER_SIZE = 32 * 1024;

    static final class Call {
        private final AtomicBoolean cancelled = new AtomicBoolean(false);
        private volatile HttpsURLConnection connection;

        void cancel() {
            cancelled.set(true);
            HttpsURLConnection active = connection;
            if (active != null) active.disconnect();
        }

        private boolean isCancelled() { return cancelled.get(); }
        private void setConnection(HttpsURLConnection value) { connection = value; }
        private void clearConnection(HttpsURLConnection value) {
            if (connection == value) connection = null;
        }
    }

    static final class Result {
        final int status;
        final String body;
        final String diagnostic;

        Result(int status, String body, String diagnostic) {
            this.status = status;
            this.body = body == null ? "" : body;
            this.diagnostic = diagnostic == null ? "NATIVE_UNKNOWN" : diagnostic;
        }

        boolean isTransportFailure() { return status == 0; }
    }

    private BChatNativeMediaUploader() { }

    static Result upload(Call call, String origin, String grantId, String secret, File source,
                         int expectedSize, String mime) {
        if (!validInputs(call, origin, grantId, secret) || source == null || expectedSize < 1
                || source.length() != expectedSize || mime == null || mime.isEmpty())
            return new Result(0, "", "NATIVE_UPLOAD_INPUT");
        HttpsURLConnection connection = null;
        try {
            connection = open(call, endpoint(origin, grantId, "/content"), grantId, secret, "POST");
            if (connection == null) return new Result(0, "", "NATIVE_UPLOAD_CANCELLED");
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", mime);
            connection.setFixedLengthStreamingMode((long) expectedSize);
            byte[] buffer = new byte[BUFFER_SIZE];
            int total = 0;
            try (InputStream input = new BufferedInputStream(new FileInputStream(source));
                 BufferedOutputStream output = new BufferedOutputStream(connection.getOutputStream())) {
                int count;
                while ((count = input.read(buffer)) != -1) {
                    if (call.isCancelled()) return new Result(0, "", "NATIVE_UPLOAD_CANCELLED");
                    if (count <= 0 || count > expectedSize - total)
                        return new Result(0, "", "NATIVE_UPLOAD_SIZE_CHANGED");
                    output.write(buffer, 0, count);
                    total += count;
                }
                if (total != expectedSize) return new Result(0, "", "NATIVE_UPLOAD_SIZE_CHANGED");
                output.flush();
            }
            return response(call, connection);
        } catch (IOException failure) {
            return new Result(0, "", call.isCancelled() ? "NATIVE_UPLOAD_CANCELLED" : "NATIVE_UPLOAD_IO");
        } finally {
            if (connection != null) {
                call.clearConnection(connection);
                connection.disconnect();
            }
        }
    }

    static Result status(Call call, String origin, String grantId, String secret) {
        if (!validInputs(call, origin, grantId, secret)) return new Result(0, "", "NATIVE_STATUS_INPUT");
        HttpsURLConnection connection = null;
        try {
            connection = open(call, endpoint(origin, grantId, ""), grantId, secret, "GET");
            if (connection == null) return new Result(0, "", "NATIVE_STATUS_CANCELLED");
            return response(call, connection);
        } catch (IOException failure) {
            return new Result(0, "", call.isCancelled() ? "NATIVE_STATUS_CANCELLED" : "NATIVE_STATUS_IO");
        } finally {
            if (connection != null) {
                call.clearConnection(connection);
                connection.disconnect();
            }
        }
    }

    private static boolean validInputs(Call call, String origin, String grantId, String secret) {
        return call != null && origin != null && origin.startsWith("https://")
                && grantId != null && grantId.matches("[0-9a-f-]{36}")
                && secret != null && secret.matches("[A-Za-z0-9_-]{43,128}");
    }

    private static URL endpoint(String origin, String grantId, String suffix) throws IOException {
        URL target = new URL(origin + "/bchat/api/v2/mobile-upload-grants/" + grantId + suffix);
        if (!"https".equalsIgnoreCase(target.getProtocol()) || target.getUserInfo() != null
                || target.getQuery() != null || target.getRef() != null) {
            throw new IOException("Unexpected native upload endpoint");
        }
        return target;
    }

    private static HttpsURLConnection open(Call call, URL target, String grantId, String secret,
                                           String method) throws IOException {
        if (call.isCancelled()) return null;
        HttpsURLConnection connection = (HttpsURLConnection) target.openConnection();
        call.setConnection(connection);
        connection.setRequestMethod(method);
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
        connection.setUseCaches(false);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("Authorization", "BChatUpload " + grantId + "." + secret);
        connection.setRequestProperty("Cache-Control", "no-store");
        return connection;
    }

    private static Result response(Call call, HttpsURLConnection connection) throws IOException {
        if (call.isCancelled()) return new Result(0, "", "NATIVE_RESPONSE_CANCELLED");
        int status = connection.getResponseCode();
        if (status >= 300 && status < 400) return new Result(0, "", "NATIVE_REDIRECT_REJECTED");
        String type = connection.getHeaderField("Content-Type");
        if (type == null || !"application/json".equals(type.split(";", 2)[0].trim().toLowerCase()))
            return new Result(0, "", "NATIVE_RESPONSE_TYPE");
        InputStream source = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
        if (source == null) return new Result(0, "", "NATIVE_RESPONSE_EMPTY");
        try (InputStream input = new BufferedInputStream(source);
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[2048];
            int total = 0, count;
            while ((count = input.read(buffer)) != -1) {
                if (call.isCancelled()) return new Result(0, "", "NATIVE_RESPONSE_CANCELLED");
                if (count <= 0 || total + count > RESPONSE_LIMIT)
                    return new Result(0, "", "NATIVE_RESPONSE_SIZE");
                output.write(buffer, 0, count);
                total += count;
            }
            return new Result(status, output.toString("UTF-8"), "");
        }
    }
}
