package com.baseer.bchat.trial.session;

import android.os.Handler;
import android.os.Looper;
import android.webkit.CookieManager;
import com.facebook.react.modules.network.ForwardingCookieHandler;
import com.facebook.react.modules.network.OkHttpClientProvider;
import java.net.URI;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/** Installed before ReactNative load. No JS cookie bridge, WebView login or cookie copying. */
public final class BaseerSessionNetworking {
  private static OriginCookieJar installed;
  private static final ExecutorService FLUSH = Executors.newSingleThreadExecutor(runnable -> {
    Thread thread = new Thread(runnable, "bchat-cookie-commit");
    thread.setDaemon(true);
    return thread;
  });
  private BaseerSessionNetworking() {}

  public static synchronized void install(String origin) {
    if (installed != null) return;
    Handler main = new Handler(Looper.getMainLooper());
    CommitCookieHandler handler = new CommitCookieHandler(new ForwardingCookieHandler(), new CommitCookieHandler.Writer() {
      @Override public boolean isMainThread() { return Looper.myLooper() == Looper.getMainLooper(); }
      @Override public void write(URI uri, List<String> cookies, CommitCookieHandler.Completion completion) {
        if (!main.post(() -> {
          try {
            CookieManager manager = CookieManager.getInstance();
            AtomicInteger remaining = new AtomicInteger(cookies.size());
            AtomicBoolean accepted = new AtomicBoolean(true);
            for (String cookie : cookies) {
              manager.setCookie(uri.toString(), cookie, success -> {
                if (!Boolean.TRUE.equals(success)) accepted.set(false);
                if (remaining.decrementAndGet() == 0) {
                  // flush can perform disk I/O; never hold the main thread waiting for it.
                  FLUSH.execute(() -> {
                    try { manager.flush(); completion.complete(accepted.get()); }
                    catch (Exception ignored) { completion.complete(false); }
                  });
                }
              });
            }
          } catch (Exception ignored) { completion.complete(false); }
        })) completion.complete(false);
      }
    }, 5000);
    OriginCookieJar jar = new OriginCookieJar(origin, handler);
    OkHttpClientProvider.setOkHttpClientFactory(() -> OkHttpClientProvider.createClientBuilder()
        .cookieJar(jar).addInterceptor(jar).followRedirects(false).followSslRedirects(false).build());
    // Fail closed if a template change initialized the shared client before this registration.
    if (OkHttpClientProvider.getOkHttpClient().cookieJar() != jar) {
      throw new IllegalStateException("native_cookie_factory_order");
    }
    installed = jar;
  }
}
