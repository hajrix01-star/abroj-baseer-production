package com.baseer.bwork.session;

import java.io.IOException;
import java.net.CookieHandler;
import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.URI;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import okhttp3.Cookie;
import okhttp3.CookieJar;
import okhttp3.HttpUrl;
import okhttp3.OkHttpClient;
import okhttp3.Protocol;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.ResponseBody;
import okio.BufferedSource;
import okio.Buffer;

/** Synthetic only. Uses installed RN interface, JavaNetCookieJar and OkHttp; no socket or Android. */
public final class SessionCookieHarness {
  private static final String ORIGIN = "https://qa.example.test";
  private static int assertions;
  private static final AtomicInteger closed = new AtomicInteger();
  private static void check(boolean value, String name) {
    assertions++;
    if (!value) throw new AssertionError(name);
  }
  private static final class Store extends CookieHandler implements CommitCookieHandler.Writer {
    final CookieManager nativeStore = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
    boolean delay;
    boolean reject;
    boolean main;
    boolean readFails;
    volatile Runnable release;
    final CountDownLatch queued = new CountDownLatch(1);
    @Override public boolean isMainThread() { return main; }
    @Override public Map<String, List<String>> get(URI uri, Map<String, List<String>> headers) throws IOException {
      if (readFails) throw new IOException("synthetic");
      return nativeStore.get(uri, headers);
    }
    @Override public void put(URI uri, Map<String, List<String>> headers) throws IOException { nativeStore.put(uri, headers); }
    @Override public void write(URI uri, List<String> cookies, CommitCookieHandler.Completion completion) {
      Runnable write = () -> {
        try {
          if (!reject) nativeStore.put(uri, Collections.singletonMap("Set-Cookie", cookies));
          completion.complete(!reject);
        } catch (IOException ignored) { completion.complete(false); }
      };
      if (delay) release = write; else write.run();
      queued.countDown();
    }
  }
  private static OriginCookieJar jar(Store store, long timeout) {
    return new OriginCookieJar(ORIGIN, new CommitCookieHandler(store, store, timeout));
  }
  private static Cookie cookie(String value) { return Cookie.parse(HttpUrl.get(ORIGIN + "/web/session/authenticate"), value); }
  private static String value(OriginCookieJar jar, String path) {
    List<Cookie> cookies = jar.loadForRequest(HttpUrl.get(ORIGIN + path));
    for (Cookie cookie : cookies) if (cookie.name().equals("session_id")) return cookie.value();
    return "";
  }
  private static Response call(OriginCookieJar jar, String path, AtomicInteger posts, Cookie setCookie) throws IOException {
    // Last application interceptor is a synthetic server; real OkHttp still executes our outer
    // interceptor and real cookie adapter. No network, credentials or mock RN interfaces.
    OkHttpClient client = new OkHttpClient.Builder().cookieJar(jar).addInterceptor(jar).addInterceptor(chain -> {
      posts.incrementAndGet();
      jar.loadForRequest(chain.request().url());
      if (setCookie != null) jar.saveFromResponse(chain.request().url(), Collections.singletonList(setCookie));
      return new Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("OK")
          .body(new ResponseBody() {
            private final Buffer content = new Buffer().writeUtf8("synthetic");
            @Override public okhttp3.MediaType contentType() { return null; }
            @Override public long contentLength() { return 9; }
            @Override public BufferedSource source() { return content; }
            @Override public void close() { closed.incrementAndGet(); super.close(); }
          }).build();
    }).build();
    return client.newCall(new Request.Builder().url(ORIGIN + path).post(okhttp3.RequestBody.create(null, "synthetic")).build()).execute();
  }
  private static void failure(OriginCookieJar jar, AtomicInteger posts, Cookie cookie, String expected) throws Exception {
    try (Response ignored = call(jar, "/web/session/authenticate", posts, cookie)) { throw new AssertionError("expected " + expected); }
    catch (IOException error) { check(error.getMessage().equals(expected), expected); }
  }
  public static void main(String[] args) throws Exception {
    Store store = new Store();
    OriginCookieJar jar = jar(store, 1000);
    AtomicInteger posts = new AtomicInteger();
    try (Response ignored = call(jar, "/web/session/authenticate", posts, cookie("session_id=first; Path=/; Secure; HttpOnly"))) {}
    check(value(jar, "/bwork/api/v2/bootstrap").equals("first"), "auth to bootstrap");
    check(value(jar, "/bwork/api/v2/media/upload").equals("first"), "same upload jar");
    check(value(jar, "/bwork/api/v2/media/7/download").equals("first"), "same download jar");
    try (Response ignored = call(jar, "/web/session/authenticate", posts, cookie("session_id=rotated; Path=/; Secure"))) {}
    check(value(jar, "/bwork/api/v2/bootstrap").equals("rotated"), "login rotation replacement");
    jar.setCookieJar(CookieJar.NO_COOKIES);
    jar.removeCookieJar();
    check(value(jar, "/bwork/api/v2/bootstrap").equals("rotated"), "RN and BlobUtil cannot replace; detach preserves persistent store");
    OriginCookieJar restarted = jar(store, 1000);
    check(value(restarted, "/bwork/api/v2/bootstrap").equals("rotated"), "new container reuses persistent native store");
    check(jar.loadForRequest(HttpUrl.get("http://qa.example.test/")).isEmpty(), "HTTP excluded");
    check(jar.loadForRequest(HttpUrl.get("https://qa.example.test:444/")).isEmpty(), "cross port excluded");
    check(jar.loadForRequest(HttpUrl.get("https://other.example.test/")).isEmpty(), "cross host excluded");
    jar.saveFromResponse(HttpUrl.get("https://other.example.test/"), Collections.singletonList(Cookie.parse(HttpUrl.get("https://other.example.test/"), "session_id=evil; Path=/")));
    check(value(jar, "/").equals("rotated"), "crossorigin response excluded");
    try (Response ignored = call(jar, "/web/session/destroy", posts, cookie("session_id=; Max-Age=0; Path=/; Secure"))) {}
    check(value(jar, "/").isEmpty(), "logout expiry committed");
    try (Response ignored = call(jar, "/web/session/authenticate", posts, cookie("session_id=expired; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/"))) {}
    check(value(jar, "/").isEmpty(), "expired cookie excluded");
    try (Response ignored = call(jar, "/web/session/authenticate", posts, cookie("session_id=scoped; Path=/only; Secure"))) {}
    check(value(jar, "/outside").isEmpty() && value(jar, "/only/file").equals("scoped"), "native path filtering");

    Store delayed = new Store(); delayed.delay = true;
    OriginCookieJar delayedJar = jar(delayed, 1000);
    AtomicInteger delayedPosts = new AtomicInteger();
    List<Throwable> errors = Collections.synchronizedList(new ArrayList<>());
    CountDownLatch returned = new CountDownLatch(1);
    Thread auth = new Thread(() -> { try (Response ignored = call(delayedJar, "/web/session/authenticate", delayedPosts, cookie("session_id=late; Path=/"))) {} catch (Throwable error) { errors.add(error); } finally { returned.countDown(); } });
    auth.start(); check(delayed.queued.await(1, TimeUnit.SECONDS), "native write queued");
    check(!returned.await(30, TimeUnit.MILLISECONDS), "auth response waits for native callback");
    Thread next = new Thread(() -> { try (Response ignored = call(delayedJar, "/bwork/api/v2/bootstrap", delayedPosts, null)) {} catch (Throwable error) { errors.add(error); } });
    next.start(); Thread.sleep(30);
    check(delayedPosts.get() == 1, "next request not sent before commit");
    delayed.release.run(); auth.join(1000); next.join(1000);
    check(errors.isEmpty() && delayedPosts.get() == 2, "callback releases next request");
    check(value(delayedJar, "/").equals("late"), "callback native state visible");

    Store timeout = new Store(); timeout.delay = true;
    OriginCookieJar timeoutJar = jar(timeout, 20); AtomicInteger timeoutPosts = new AtomicInteger();
    int beforeClose = closed.get();
    failure(timeoutJar, timeoutPosts, cookie("session_id=old; Path=/"), "native_cookie_commit_timeout");
    check(closed.get() == beforeClose + 1, "post-commit failure closes response body");
    failure(timeoutJar, timeoutPosts, cookie("session_id=new; Path=/"), "native_cookie_commit_timeout");
    check(timeoutPosts.get() == 1, "unsettled timeout prevents next POST and retry");
    timeout.release.run(); timeout.delay = false;
    try (Response ignored = call(timeoutJar, "/web/session/destroy", timeoutPosts, cookie("session_id=; Max-Age=0; Path=/"))) {}
    check(value(timeoutJar, "/").isEmpty(), "late old commit settles before strict destroy");
    try (Response ignored = call(timeoutJar, "/web/session/authenticate", timeoutPosts, cookie("session_id=new; Path=/"))) {}
    check(value(timeoutJar, "/").equals("new"), "old callback cannot overwrite new login");

    Store rejected = new Store(); rejected.reject = true;
    OriginCookieJar rejectedJar = jar(rejected, 100); AtomicInteger rejectedPosts = new AtomicInteger();
    failure(rejectedJar, rejectedPosts, cookie("session_id=bad; Path=/"), "native_cookie_commit_failed");
    failure(rejectedJar, rejectedPosts, cookie("session_id=new; Path=/"), "native_cookie_commit_failed");
    check(rejectedPosts.get() == 1, "rejected callback permanently fails closed");
    Store main = new Store(); main.main = true;
    AtomicInteger mainPosts = new AtomicInteger();
    failure(jar(main, 100), mainPosts, cookie("session_id=bad; Path=/"), "native_cookie_main_thread");
    check(mainPosts.get() == 0, "main thread never blocks or sends");

    Store quota = new Store(); OriginCookieJar quotaJar = jar(quota, 100);
    List<Cookie> oversized = new ArrayList<>();
    for (int i = 0; i < 33; i++) oversized.add(cookie("cookie" + i + "=x; Path=/"));
    quotaJar.saveFromResponse(HttpUrl.get(ORIGIN + "/"), oversized);
    failure(quotaJar, new AtomicInteger(), null, "native_cookie_commit_failed");
    check(quota.nativeStore.getCookieStore().getCookies().isEmpty(), "quota rejects before native mutation");
    Store bytes = new Store(); OriginCookieJar bytesJar = jar(bytes, 100);
    failure(bytesJar, new AtomicInteger(), cookie("session_id=" + "x".repeat(16385) + "; Path=/"), "native_cookie_commit_failed");
    check(bytes.nativeStore.getCookieStore().getCookies().isEmpty(), "byte quota rejects before native mutation");
    Store parent = new Store(); OriginCookieJar parentJar = jar(parent, 100);
    try (Response ignored = call(parentJar, "/", new AtomicInteger(), cookie("session_id=parent; Domain=example.test; Path=/"))) {}
    check(value(parentJar, "/").isEmpty(), "parent-domain cookie refused");
    Store unreadable = new Store(); unreadable.readFails = true;
    OriginCookieJar unreadableJar = jar(unreadable, 100); AtomicInteger unreadablePosts = new AtomicInteger();
    failure(unreadableJar, unreadablePosts, null, "native_cookie_commit_failed");
    failure(unreadableJar, unreadablePosts, null, "native_cookie_commit_failed");
    check(unreadablePosts.get() == 1, "native read failure cannot be swallowed into successful authentication");
    System.out.println("PASS " + assertions + " native cookie assertions (installed RN/OkHttp; synthetic native store, no device claim)");
  }
}
