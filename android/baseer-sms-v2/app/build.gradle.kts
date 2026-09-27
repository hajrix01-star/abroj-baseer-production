plugins { id("com.android.application") }

android {
    namespace = "sa.abroj.baseersms.v2"
    compileSdk = 36
    buildToolsVersion = "36.1.0"
    defaultConfig {
        applicationId = "sa.abroj.baseersms.v2"
        minSdk = 26
        targetSdk = 36
        versionCode = 6
        versionName = "2.0.5-qa"
    }
    buildFeatures { buildConfig = true }
}

dependencies {
    implementation("androidx.work:work-runtime:2.10.1")
    implementation("com.google.android.gms:play-services-code-scanner:16.1.0")
}
