package com.baseer.bwork.session;

import com.facebook.react.modules.network.CookieJarContainer;
import java.io.IOException;
import java.net.ProtocolException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import okhttp3.Call;
import okhttp3.Cookie;
import okhttp3.CookieJar;
import okhttp3.Headers;
import okhttp3.HttpUrl;
import okhttp3.Interceptor;
import okhttp3.JavaNetCookieJar;
import okhttp3.Response;
import okhttp3.RequestBody;
import okhttp3.MediaType;
import okio.BufferedSink;

/** One app-owned persistent native store; RN/BlobUtil cannot replace it with an async writer. */
public final class OriginCookieJar implements CookieJarContainer, Interceptor {
  private final HttpUrl origin;
  private final CommitCookieHandler handler;
  private final JavaNetCookieJar delegate;
  private final Object requests = new Object();
  private final Map<Call, Boolean> avatarAttempts = new WeakHashMap<>();

  public OriginCookieJar(String fixedOrigin, CommitCookieHandler handler) {
    HttpUrl parsed = HttpUrl.get(fixedOrigin);
    if (!parsed.isHttps() || !parsed.username().isEmpty() || !parsed.password().isEmpty()
        || !parsed.encodedPath().equals("/") || parsed.query() != null || parsed.fragment() != null) {
      throw new IllegalArgumentException("cookie_origin");
    }
    this.origin = parsed;
    this.handler = handler;
    this.delegate = new JavaNetCookieJar(handler);
  }

  private boolean allowed(HttpUrl url) {
    return url.isHttps() && url.host().equals(origin.host()) && url.port() == origin.port();
  }
  /** Claim the actual network attempt, not an outer cloned request which BlobUtil discards. */
  public Interceptor avatarNetworkGuard() {
    return chain -> {
      HttpUrl url = chain.request().url();
      if (!allowed(url) || !chain.request().method().equals("POST") || url.query() != null
          || url.fragment() != null || !url.encodedPath().matches("/bwork/api/v2/rooms/[1-9][0-9]*/avatar")) {
        return chain.proceed(chain.request());
      }
      synchronized (avatarAttempts) {
        if (avatarAttempts.containsKey(chain.call())) throw new ProtocolException("avatar_upload_replay_blocked");
        avatarAttempts.put(chain.call(), Boolean.TRUE);
      }
      RequestBody body = chain.request().body();
      if (body == null) throw new ProtocolException("avatar_upload_body_required");
      RequestBody once = new RequestBody() {
        private final AtomicBoolean written = new AtomicBoolean();
        @Override public MediaType contentType() { return body.contentType(); }
        @Override public long contentLength() throws IOException { return body.contentLength(); }
        @Override public boolean isOneShot() { return true; }
        @Override public void writeTo(BufferedSink sink) throws IOException {
          if (!written.compareAndSet(false, true)) throw new ProtocolException("avatar_upload_replay_blocked");
          body.writeTo(sink);
        }
      };
      return chain.proceed(chain.request().newBuilder().method("POST", once).build());
    };
  }

  @Override public void setCookieJar(CookieJar ignored) { /* App-owned writer is authoritative. */ }
  @Override public void removeCookieJar() {
    // RN module detach is not logout. Like the original native CookieManager, persist across reload.
    // Server /web/session/destroy expiry is committed through saveFromResponse instead.
  }

  @Override public void saveFromResponse(HttpUrl url, List<Cookie> cookies) {
    if (!allowed(url)) return;
    List<Cookie> scoped = new ArrayList<>();
    for (Cookie cookie : cookies) {
      // Never install a parent-domain cookie that could leak to another native app destination.
      if (cookie.domain().equals(origin.host())) scoped.add(cookie);
    }
    delegate.saveFromResponse(url, scoped);
  }

  @Override public List<Cookie> loadForRequest(HttpUrl url) {
    if (!allowed(url)) return Collections.emptyList();
    List<Cookie> result = new ArrayList<>();
    // CookieManager applies the original path/domain/secure/expiry policy before returning headers.
    for (Cookie cookie : delegate.loadForRequest(url)) {
      try {
        new Headers.Builder().add(cookie.name(), cookie.value());
        if (cookie.matches(url)) result.add(cookie);
      } catch (IllegalArgumentException ignored) { /* Match RN header validation. */ }
    }
    return result;
  }

  @Override public Response intercept(Chain chain) throws IOException {
    if (!allowed(chain.request().url())) return chain.proceed(chain.request());
    handler.checkThread(); // Reject before even acquiring a monitor held by a worker request.
    // An application interceptor is outside RetryAndFollowUpInterceptor. Commit failure must not
    // trigger an automatic POST retry. The lock ends at headers+commit, not body consumption.
    synchronized (requests) {
      handler.awaitReady();
      Response response = chain.proceed(chain.request());
      try {
        handler.awaitReady();
        // BridgeInterceptor has already saved cookies and the native network observer has seen
        // them. BlobUtil exports final headers to JS, so strip secrets only at this outer boundary.
        return response.newBuilder().removeHeader("Set-Cookie").removeHeader("Set-Cookie2").build();
      } catch (IOException error) {
        response.close();
        throw error;
      }
    }
  }
}
