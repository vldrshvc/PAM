plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "ie.yarodev.pam"
    compileSdk = 35

    defaultConfig {
        applicationId = "ie.yarodev.pam"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
        // The server the app and widget talk to. Override for a local build with
        // -PpamBaseUrl=http://10.0.2.2:8000 (emulator) or your LAN address.
        val baseUrl = (project.findProperty("pamBaseUrl") as String?) ?: "https://pam-u8qh.onrender.com"
        buildConfigField("String", "BASE_URL", "\"$baseUrl\"")
        manifestPlaceholders["pamHost"] = baseUrl.removePrefix("https://").removePrefix("http://").substringBefore("/")
        manifestPlaceholders["pamBaseUrl"] = baseUrl
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    buildFeatures {
        buildConfig = true
        compose = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // Trusted Web Activity: the existing web app, full screen, Chrome-backed.
    implementation("com.google.androidbrowserhelper:androidbrowserhelper:2.6.0")

    // Home-screen widget.
    implementation("androidx.glance:glance-appwidget:1.1.1")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    implementation("androidx.security:security-crypto:1.0.0")

    // Widget login screen (plain Views, no Compose UI needed for one form).
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("com.google.android.material:material:1.12.0")
}
