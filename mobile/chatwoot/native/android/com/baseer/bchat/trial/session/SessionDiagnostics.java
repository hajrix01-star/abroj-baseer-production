package com.baseer.bchat.trial.session;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;
import okhttp3.Cookie;
import okhttp3.Headers;
import okhttp3.HttpUrl;
import okhttp3.Interceptor;
import okhttp3.Request;
import okhttp3.Response;

/** Network-only observation, after BridgeInterceptor adds the actual outbound Cookie header.
 * The only exported data is I[01]A[01]S[01]M[01]L[01]. No raw cookie/digest/Location is logged or exported.
 */
public final class SessionDiagnostics implements Interceptor {
  public static final String HEADER = "X-Baseer-Native-Session";
  private static final int MAX_HEADERS = 32;
  private static final int MAX_BYTES = 16384;
  private final HttpUrl origin;
  private final Object state = new Object();
  private long epoch;
  private Observation reference = new Observation(false, false, null);
  private static final class Observation {
    final boolean issued;
    final boolean eligible;
    final byte[] digest;
    Observation(boolean issued, boolean eligible, byte[] digest) {
      this.issued = issued; this.eligible = eligible; this.digest = digest;
    }
  }
  private static final class Outgoing {
    final boolean present;
    final byte[] digest;
    Outgoing(boolean present, byte[] digest) { this.present = present; this.digest = digest; }
  }

  public SessionDiagnostics(String fixedOrigin) { origin = HttpUrl.get(fixedOrigin); }

  private boolean sameOrigin(HttpUrl url) {
    return url.isHttps() && url.host().equals(origin.host()) && url.port() == origin.port();
  }
  private boolean exact(Request request, String method, String path) {
    HttpUrl url = request.url();
    return sameOrigin(url) && url.username().isEmpty() && url.password().isEmpty()
        && url.query() == null && url.fragment() == null
        && request.method().equals(method) && url.encodedPath().equals(path);
  }
  private static byte[] digest(String value) throws Exception {
    return MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
  }
  private static boolean bounded(List<String> headers) {
    if (headers.size() > MAX_HEADERS) return false;
    int bytes = 0;
    for (String header : headers) {
      int size = header.getBytes(StandardCharsets.UTF_8).length;
      if (size > MAX_BYTES - bytes) return false;
      bytes += size;
    }
    return true;
  }
  private Observation issued(HttpUrl url, Headers headers) {
    try {
      List<String> values = headers.values("Set-Cookie");
      if (!bounded(values)) return new Observation(false, false, null);
      int count = 0;
      boolean parsed = false;
      Cookie candidate = null;
      for (String value : values) {
        int equals = value.indexOf('=');
        if (equals < 0 || !value.substring(0, equals).trim().equals("session_id")) continue;
        count++;
        candidate = Cookie.parse(url, value);
        if (candidate != null && candidate.name().equals("session_id")) parsed = true;
      }
      if (count != 1 || candidate == null || !candidate.name().equals("session_id")
          || candidate.value().isEmpty() || !candidate.domain().equals(origin.host())
          || !candidate.path().equals("/") || candidate.expiresAt() <= System.currentTimeMillis()) return new Observation(parsed, false, null);
      return new Observation(true, true, digest(candidate.value()));
    } catch (Exception ignored) { return new Observation(false, false, null); }
  }
  private static Outgoing sent(Headers headers) {
    try {
      List<String> values = headers.values("Cookie");
      if (!bounded(values)) return new Outgoing(false, null);
      int count = 0;
      int pairs = 0;
      String candidate = null;
      boolean present = false;
      for (String value : values) {
        for (String pair : value.split(";", -1)) {
          if (++pairs > MAX_HEADERS) return new Outgoing(false, null);
          int equals = pair.indexOf('=');
          if (equals < 0 || !pair.substring(0, equals).trim().equals("session_id")) continue;
          count++;
          candidate = pair.substring(equals + 1).trim();
          if (!candidate.isEmpty()) present = true;
        }
      }
      if (count != 1 || candidate == null || candidate.isEmpty()) return new Outgoing(present, null);
      return new Outgoing(true, digest(candidate));
    } catch (Exception ignored) { return new Outgoing(false, null); }
  }
  private boolean loginRedirect(Response response) {
    try {
      List<String> locations = response.headers().values("Location");
      if (response.code() != 303 || locations.size() != 1 || !bounded(locations)) return false;
      HttpUrl target = response.request().url().resolve(locations.get(0));
      return target != null && sameOrigin(target) && target.username().isEmpty() && target.password().isEmpty()
          && target.encodedPath().equals("/web/login");
    } catch (Exception ignored) { return false; }
  }

  @Override public Response intercept(Chain chain) throws IOException {
    Request request = chain.request();
    boolean auth = exact(request, "POST", "/web/session/authenticate");
    boolean destroy = exact(request, "POST", "/web/session/destroy");
    boolean bootstrap = exact(request, "GET", "/bchat/api/v2/bootstrap");
    final long exchangeEpoch;
    final Observation observed;
    synchronized (state) {
      if (auth || destroy) { epoch++; reference = new Observation(false, false, null); }
      exchangeEpoch = epoch;
      observed = reference;
    }
    // Snapshot this exchange before calling the server; a concurrent reset cannot change its bits.
    Outgoing outgoing = bootstrap ? sent(request.headers()) : new Outgoing(false, null);
    Response response = chain.proceed(request); // No body reads, request mutation, retries or extra calls.
    if (auth) {
      Observation next = issued(request.url(), response.headers());
      synchronized (state) { if (epoch == exchangeEpoch) reference = next; }
    }
    Response.Builder safe = response.newBuilder().removeHeader(HEADER); // Never trust upstream spoofing.
    if (bootstrap) {
      String token = "I" + (observed.issued ? "1" : "0") + "A" + (observed.eligible ? "1" : "0")
          + "S" + (outgoing.present ? "1" : "0")
          + "M" + (observed.eligible && observed.digest != null && outgoing.digest != null && MessageDigest.isEqual(observed.digest, outgoing.digest) ? "1" : "0")
          + "L" + (loginRedirect(response) ? "1" : "0");
      safe.header(HEADER, token);
    }
    return safe.build();
  }
}
