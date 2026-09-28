import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

plugins { id("com.android.application") }

val buildTimestamp = ZonedDateTime.now(ZoneId.of("Asia/Riyadh"))
    .format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm z"))

android {
    namespace = "sa.abroj.baseersms.v2"
    compileSdk = 36
    buildToolsVersion = "36.1.0"
    defaultConfig {
        // Keep the installed Live application's identity so Android accepts this
        // as an update to the owner-controlled Baseer SMS app.
        applicationId = "sa.abroj.baseersms"
        minSdk = 26
        targetSdk = 36
        versionCode = 209
        versionName = "2.0.9"
        buildConfigField("String", "BUILD_TIMESTAMP", "\"$buildTimestamp\"")
        buildConfigField("String", "ENVIRONMENT_LABEL", "\"Live\"")
    }
    buildFeatures { buildConfig = true }
}

dependencies {
    implementation("androidx.work:work-runtime:2.10.1")
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0")
}
