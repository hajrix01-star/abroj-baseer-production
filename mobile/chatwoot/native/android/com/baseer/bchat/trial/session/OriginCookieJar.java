package com.baseer.bchat.trial.session;

import com.facebook.react.modules.network.CookieJarContainer;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import okhttp3.Cookie;
import okhttp3.CookieJar;
import okhttp3.Headers;
import okhttp3.HttpUrl;
import okhttp3.Interceptor;
import okhttp3.JavaNetCookieJar;
import okhttp3.Response;

/** One app-owned persistent native store; RN/BlobUtil cannot replace it with an async writer. */
public final class OriginCookieJar implements CookieJarContainer, Interceptor {
  private final HttpUrl origin;
  private final CommitCookieHandler handler;
  private final JavaNetCookieJar delegate;
  private final Object requests = new Object();

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
