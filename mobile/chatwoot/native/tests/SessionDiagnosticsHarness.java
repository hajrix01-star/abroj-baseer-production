package com.baseer.bchat.trial.session;

import java.io.IOException;
import java.lang.reflect.Proxy;
import java.net.CookieHandler;
import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.URI;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import okhttp3.Headers;
import okhttp3.HttpUrl;
import okhttp3.Interceptor;
import okhttp3.Protocol;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;
import okhttp3.internal.http.BridgeInterceptor;

/** Installed OkHttp BridgeInterceptor feeds the diagnostic observer actual outbound headers.
 * Synthetic server/native store only; no socket, real account, cookie value logging or device claim.
 */
public final class SessionDiagnosticsHarness {
  private static final String ORIGIN = "https://qa.example.test";
  private static final String BOOTSTRAP = "/bchat/api/v2/bootstrap";
  private static int assertions;
  private static void check(boolean value, String name) {
    assertions++;
    if (!value) throw new AssertionError(name);
  }
  private interface Server { Response respond(Request request) throws IOException; }
  private static Interceptor.Chain chain(Request request, Server server) {
    return (Interceptor.Chain) Proxy.newProxyInstance(Interceptor.Chain.class.getClassLoader(), new Class<?>[] { Interceptor.Chain.class }, (proxy, method, args) -> {
      if (method.getName().equals("request")) return request;
      if (method.getName().equals("proceed")) return server.respond((Request) args[0]);
      if (method.getReturnType() == int.class) return 0;
      if (method.getReturnType() == Interceptor.Chain.class) return proxy;
      return null;
    });
  }
  private static Request request(String method, String path, String... cookie) {
    Request.Builder value = new Request.Builder().url(path.startsWith("http") ? path : ORIGIN + path);
    value.method(method, method.equals("POST") ? RequestBody.create(null, "synthetic") : null);
    for (String header : cookie) value.addHeader("Cookie", header);
    return value.build();
  }
  private static Response response(Request request, int status, Headers headers) {
    return new Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(status).message("synthetic")
        .headers(headers).body(ResponseBody.create(null, "unread synthetic body")).build();
  }
  private static Response observe(SessionDiagnostics diagnostic, Request request, int status, Headers headers) throws IOException {
    return diagnostic.intercept(chain(request, wire -> response(wire, status, headers)));
  }
  private static void auth(SessionDiagnostics diagnostic, String... setCookies) throws IOException {
    Headers.Builder headers = new Headers.Builder().add("x-baseer-native-session", "spoof");
    for (String cookie : setCookies) headers.add("Set-Cookie", cookie);
    try (Response response = observe(diagnostic, request("POST", "/web/session/authenticate"), 200, headers.build())) {
      check(response.header(SessionDiagnostics.HEADER) == null, "auth never exports private header");
    }
  }
  private static String token(SessionDiagnostics diagnostic, String... cookies) throws IOException {
    try (Response response = observe(diagnostic, request("GET", BOOTSTRAP, cookies), 303,
        new Headers.Builder().add("Location", "/web/login?db=not-exported").add("X-BASEER-NATIVE-SESSION", "spoof").build())) {
      String token = response.header(SessionDiagnostics.HEADER);
      check(token != null && token.matches("I[01]A[01]S[01]M[01]L[01]"), "only exact diagnostic grammar leaves native code");
      check(response.headers().values(SessionDiagnostics.HEADER).size() == 1, "upstream spoof replaced case-insensitively");
      check(response.body().string().equals("unread synthetic body"), "diagnostic does not consume body");
      return token;
    }
  }
  private static final class Store extends CookieHandler implements CommitCookieHandler.Writer {
    final CookieManager store = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
    @Override public boolean isMainThread() { return false; }
    @Override public Map<String, List<String>> get(URI uri, Map<String, List<String>> headers) throws IOException { return store.get(uri, headers); }
    @Override public void put(URI uri, Map<String, List<String>> headers) throws IOException { store.put(uri, headers); }
    @Override public void write(URI uri, List<String> values, CommitCookieHandler.Completion completion) {
      try { store.put(uri, Collections.singletonMap("Set-Cookie", values)); completion.complete(true); }
      catch (IOException ignored) { completion.complete(false); }
    }
  }
  public static void main(String[] args) throws Exception {
    SessionDiagnostics diagnostic = new SessionDiagnostics(ORIGIN);
    check(token(diagnostic).equals("I0A0S0M0L1"), "no issued or outgoing session");
    auth(diagnostic, "session_id=issued; Path=/; HttpOnly; Max-Age=600");
    check(token(diagnostic, "session_id=issued").equals("I1A1S1M1L1"), "eligible session sent and matches");
    check(token(diagnostic, "session_id=rotated").equals("I1A1S1M0L1"), "rotated outbound digest differs");
    check(token(diagnostic).equals("I1A1S0M0L1"), "issued but not sent");
    check(token(diagnostic, "session_id=issued", "session_id=issued").equals("I1A1S1M0L1"), "duplicate outgoing is present but never a match");
    check(token(diagnostic, "other=x; session_id=issued; session_id=other").equals("I1A1S1M0L1"), "duplicate in single header cannot match");
    check(token(diagnostic, "session_id=").equals("I1A1S0M0L1"), "empty outbound not present");
    auth(diagnostic, "session_id=issued; Path=/only; Max-Age=600");
    check(token(diagnostic, "session_id=issued").equals("I1A0S1M0L1"), "parsed path rejected by jar eligibility");
    auth(diagnostic, "session_id=issued; Domain=example.test; Path=/; Max-Age=600");
    check(token(diagnostic, "session_id=issued").equals("I1A0S1M0L1"), "parent domain parsed but ineligible");
    auth(diagnostic, "session_id=issued; Domain=unrelated.test; Path=/; Max-Age=600");
    check(token(diagnostic, "session_id=issued").equals("I0A0S1M0L1"), "unparseable foreign domain has no reference");
    auth(diagnostic, "session_id=; Path=/; Max-Age=600");
    check(token(diagnostic).equals("I1A0S0M0L1"), "empty issued value ineligible");
    auth(diagnostic, "session_id=expired; Path=/; Max-Age=0");
    check(token(diagnostic, "session_id=expired").equals("I1A0S1M0L1"), "expired issued value ineligible");
    auth(diagnostic, "session_id=issued; Path=/", "session_id=issued; Path=/");
    check(token(diagnostic, "session_id=issued").equals("I1A0S1M0L1"), "duplicate issued reference ineligible");
    String[] tooMany = new String[33];
    java.util.Arrays.fill(tooMany, "session_id=issued; Path=/");
    auth(diagnostic, tooMany);
    check(token(diagnostic).equals("I0A0S0M0L1"), "issued header count bound");
    auth(diagnostic, "session_id=" + "x".repeat(16385) + "; Path=/");
    check(token(diagnostic).equals("I0A0S0M0L1"), "issued byte bound");
    auth(diagnostic, "session_id=issued; Path=/");
    check(token(diagnostic, "session_id=" + "x".repeat(16385)).equals("I1A1S0M0L1"), "outgoing byte bound");
    check(token(diagnostic, "a=x;".repeat(33) + "session_id=issued").equals("I1A1S0M0L1"), "outgoing cookie pair bound");
    for (Request excludedAuth : new Request[] { request("GET", "/web/session/authenticate"), request("POST", "/web/session/authenticate?q=1"), request("POST", "https://other.example.test/web/session/authenticate"), request("POST", "https://qa.example.test:444/web/session/authenticate") }) {
      try (Response result = observe(diagnostic, excludedAuth, 200, new Headers.Builder().add("Set-Cookie", "session_id=wrong; Path=/").add("X-Baseer-Native-Session", "spoof").build())) {
        check(result.header(SessionDiagnostics.HEADER) == null, "non-exact auth does not attach diagnostics");
      }
      check(token(diagnostic, "session_id=issued").equals("I1A1S1M1L1"), "non-exact auth cannot change reference");
    }
    String[] paths = { "https://other.example.test" + BOOTSTRAP, "http://qa.example.test" + BOOTSTRAP, "https://qa.example.test:444" + BOOTSTRAP, BOOTSTRAP + "?q=1", BOOTSTRAP + "/", "/bchat/api/v2/rooms" };
    for (String path : paths) {
      try (Response excluded = observe(diagnostic, request("GET", path), 303, new Headers.Builder().add("X-Baseer-Native-Session", "spoof").build())) {
        check(excluded.header(SessionDiagnostics.HEADER) == null, "non-exact request strips spoof without attaching");
      }
    }
    try (Response excluded = observe(diagnostic, request("POST", BOOTSTRAP), 200, new Headers.Builder().add("X-Baseer-Native-Session", "spoof").build())) {
      check(excluded.header(SessionDiagnostics.HEADER) == null, "wrong bootstrap method excluded");
    }
    String[] locations = { "https://other.example.test/web/login", "http://qa.example.test/web/login", "https://qa.example.test:444/web/login", "/web/login/", "/other", "https://user@qa.example.test/web/login" };
    for (String location : locations) {
      try (Response result = observe(diagnostic, request("GET", BOOTSTRAP, "session_id=issued"), 303, new Headers.Builder().add("Location", location).build())) {
        check(result.header(SessionDiagnostics.HEADER).endsWith("L0"), "non-exact login redirect excluded");
      }
    }
    try (Response result = observe(diagnostic, request("GET", BOOTSTRAP, "session_id=issued"), 302, new Headers.Builder().add("Location", "/web/login").build())) {
      check(result.header(SessionDiagnostics.HEADER).endsWith("L0"), "only status303 qualifies");
    }
    try { diagnostic.intercept(chain(request("POST", "/web/session/destroy"), wire -> { throw new IOException("synthetic"); })); }
    catch (IOException ignored) {}
    check(token(diagnostic, "session_id=issued").equals("I0A0S1M0L1"), "destroy failure still clears reference");
    auth(diagnostic, "session_id=issued; Path=/");
    try { diagnostic.intercept(chain(request("POST", "/web/session/authenticate"), wire -> { throw new IOException("synthetic"); })); }
    catch (IOException ignored) {}
    check(token(diagnostic, "session_id=issued").equals("I0A0S1M0L1"), "new auth failure clears reference");

    CountDownLatch oldStarted = new CountDownLatch(1), releaseOld = new CountDownLatch(1);
    AtomicReference<Throwable> error = new AtomicReference<>();
    Thread oldAuth = new Thread(() -> {
      try (Response ignored = diagnostic.intercept(chain(request("POST", "/web/session/authenticate"), wire -> {
        oldStarted.countDown();
        try { if (!releaseOld.await(1, TimeUnit.SECONDS)) throw new IOException("synthetic timeout"); }
        catch (InterruptedException interrupted) { throw new IOException("synthetic interruption"); }
        return response(wire, 200, new Headers.Builder().add("Set-Cookie", "session_id=old; Path=/").build());
      }))) {} catch (Throwable failed) { error.set(failed); }
    });
    oldAuth.start(); check(oldStarted.await(1, TimeUnit.SECONDS), "old auth response held");
    auth(diagnostic, "session_id=new; Path=/"); releaseOld.countDown(); oldAuth.join(1000);
    check(error.get() == null && token(diagnostic, "session_id=new").equals("I1A1S1M1L1"), "late old auth cannot replace latest reference");

    CountDownLatch bootstrapStarted = new CountDownLatch(1), releaseBootstrap = new CountDownLatch(1);
    AtomicReference<String> exchangeToken = new AtomicReference<>();
    Thread priorBootstrap = new Thread(() -> {
      try (Response result = diagnostic.intercept(chain(request("GET", BOOTSTRAP, "session_id=new"), wire -> {
        bootstrapStarted.countDown();
        try { if (!releaseBootstrap.await(1, TimeUnit.SECONDS)) throw new IOException("synthetic timeout"); }
        catch (InterruptedException interrupted) { throw new IOException("synthetic interruption"); }
        return response(wire, 303, new Headers.Builder().add("Location", "/web/login").build());
      }))) { exchangeToken.set(result.header(SessionDiagnostics.HEADER)); } catch (Throwable failed) { error.set(failed); }
    });
    priorBootstrap.start(); check(bootstrapStarted.await(1, TimeUnit.SECONDS), "bootstrap exchange snapshot held");
    auth(diagnostic, "session_id=latest; Path=/"); releaseBootstrap.countDown(); priorBootstrap.join(1000);
    check(error.get() == null && "I1A1S1M1L1".equals(exchangeToken.get()), "concurrent auth cannot reattribute earlier bootstrap snapshot");
    check(token(diagnostic, "session_id=latest").equals("I1A1S1M1L1"), "new bootstrap uses latest auth snapshot");

    // Real installed BridgeInterceptor, not a pre-cookie application interception fixture.
    Store store = new Store();
    OriginCookieJar jar = new OriginCookieJar(ORIGIN, new CommitCookieHandler(store, store, 1000));
    SessionDiagnostics nativeDiagnostic = new SessionDiagnostics(ORIGIN);
    BridgeInterceptor bridge = new BridgeInterceptor(jar);
    AtomicReference<Request> actual = new AtomicReference<>();
    Server server = wire -> {
      actual.set(wire);
      Headers headers = wire.url().encodedPath().equals("/web/session/authenticate")
          ? new Headers.Builder().add("Set-Cookie", "session_id=bridge-session; Path=/; HttpOnly; Max-Age=600").build()
          : new Headers.Builder().add("Location", "/web/login?never=export").add("X-Baseer-Native-Session", "upstream-spoof").build();
      return response(wire, wire.url().encodedPath().equals(BOOTSTRAP) ? 303 : 200, headers);
    };
    for (Request request : new Request[] { request("POST", "/web/session/authenticate"), request("GET", BOOTSTRAP) }) {
      try (Response result = jar.intercept(chain(request, application -> bridge.intercept(chain(application,
          network -> nativeDiagnostic.intercept(chain(network, server))))))) {
        if (request.url().encodedPath().equals(BOOTSTRAP)) {
          check(actual.get().header("Cookie").contains("session_id=bridge-session"), "real BridgeInterceptor adds actual outgoing session");
          check(result.header(SessionDiagnostics.HEADER).equals("I1A1S1M1L1"), "native observer compares true outbound header after BridgeInterceptor");
        }
      }
    }
    System.out.println("PASS " + assertions + " native session diagnostic assertions (synthetic exchanges, installed OkHttp BridgeInterceptor)");
  }
}
