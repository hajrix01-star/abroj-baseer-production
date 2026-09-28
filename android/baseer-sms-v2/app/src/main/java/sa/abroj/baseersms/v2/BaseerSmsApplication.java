package sa.abroj.baseersms.v2;

import android.app.Application;

/** Runs before an Activity, receiver, or WorkManager worker in this package. */
public final class BaseerSmsApplication extends Application {
    @Override public void onCreate() {
        super.onCreate();
        SecureSettings.retireLegacyV1Dispatchers(this);
    }
}
