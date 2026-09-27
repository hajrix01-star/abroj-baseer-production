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
        applicationId = "sa.abroj.baseersms.v2"
        minSdk = 26
        targetSdk = 36
        versionCode = 8
        versionName = "2.0.7-qa"
    }
    buildFeatures { buildConfig = true }
    defaultConfig { buildConfigField("String", "BUILD_TIMESTAMP", "\"$buildTimestamp\"") }
}

dependencies {
    implementation("androidx.work:work-runtime:2.10.1")
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0")
}
