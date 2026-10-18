package com.baseer.bchat.trial.session;

import java.io.IOException;
import java.net.CookieHandler;
import java.net.URI;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** Native persistent cookie writes are acknowledged before an HTTP response is exposed.
 * No cookie values, credentials or URLs are included in failures or logs.
 */
public final class CommitCookieHandler extends CookieHandler {
  public interface Completion { void complete(boolean accepted); }
  public interface Writer {
    boolean isMainThread();
    void write(URI uri, List<String> cookies, Completion completion);
  }
  private static final int MAX_COOKIES = 32;
  private static final int MAX_BYTES = 16384;
  private final CookieHandler reader;
  private final Writer writer;
  private final long timeoutMs;
  private volatile Pending pending;
  private volatile boolean poisoned;
  private static final class Pending {
    final CountDownLatch latch = new CountDownLatch(1);
    final AtomicBoolean completed = new AtomicBoolean();
    volatile boolean accepted;
  }

  public CommitCookieHandler(CookieHandler reader, Writer writer, long timeoutMs) {
    if (timeoutMs <= 0 || timeoutMs > 5000) throw new IllegalArgumentException("cookie_timeout");
    this.reader = reader;
    this.writer = writer;
    this.timeoutMs = timeoutMs;
  }

  /** Called by the outer application interceptor, not swallowed by JavaNetCookieJar. */
  public void awaitReady() throws IOException {
    checkThread();
    if (poisoned) throw new IOException("native_cookie_commit_failed");
    Pending current = pending;
    if (current == null) return;
    try {
      if (!current.latch.await(timeoutMs, TimeUnit.MILLISECONDS)) {
        // Retain the barrier: no subsequent request can pass an unsettled old write.
        throw new IOException("native_cookie_commit_timeout");
      }
    } catch (InterruptedException error) {
      Thread.currentThread().interrupt();
      throw new IOException("native_cookie_commit_interrupted");
    }
    if (!current.accepted) {
      poisoned = true;
      throw new IOException("native_cookie_commit_failed");
    }
    if (pending == current) pending = null;
    if (poisoned) throw new IOException("native_cookie_commit_failed");
  }

  public void checkThread() throws IOException {
    if (writer.isMainThread()) throw new IOException("native_cookie_main_thread");
  }

  @Override public Map<String, List<String>> get(URI uri, Map<String, List<String>> headers) {
    if (writer.isMainThread() || poisoned || pending != null) {
      poisoned = true;
      return Collections.emptyMap();
    }
    try {
      Map<String, List<String>> value = reader.get(uri, headers);
      int bytes = 0;
      int count = 0;
      for (Map.Entry<String, List<String>> entry : value.entrySet()) {
        if (!"Cookie".equalsIgnoreCase(entry.getKey()) && !"Cookie2".equalsIgnoreCase(entry.getKey())) continue;
        for (String header : entry.getValue()) {
          bytes += header.getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
          count += header.split(";").length;
        }
      }
      if (bytes > MAX_BYTES || count > MAX_COOKIES) throw new IOException("cookie_limit");
      return value;
    } catch (Exception ignored) {
      poisoned = true;
      return Collections.emptyMap();
    }
  }

  @Override public void put(URI uri, Map<String, List<String>> headers) {
    if (writer.isMainThread() || poisoned || pending != null) { poisoned = true; return; }
    List<String> cookies = new ArrayList<>();
    int bytes = 0;
    for (Map.Entry<String, List<String>> entry : headers.entrySet()) {
      if (!"Set-Cookie".equalsIgnoreCase(entry.getKey()) && !"Set-Cookie2".equalsIgnoreCase(entry.getKey())) continue;
      for (String cookie : entry.getValue()) {
        cookies.add(cookie);
        bytes += cookie.getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
      }
    }
    if (cookies.isEmpty()) return;
    if (cookies.size() > MAX_COOKIES || bytes > MAX_BYTES) { poisoned = true; return; }
    Pending current = new Pending();
    pending = current; // Publish before dispatch; callbacks never acquire the HTTP monitor.
    try {
      writer.write(uri, Collections.unmodifiableList(cookies), accepted -> {
        if (current.completed.compareAndSet(false, true)) {
          current.accepted = accepted;
          current.latch.countDown();
        }
      });
    } catch (Exception ignored) {
      poisoned = true;
      // Partial writes may still settle late. Poison prevents all further calls this process.
      current.accepted = false;
      current.latch.countDown();
    }
  }
}
