# PAM for Android

Two things in one APK:

- **The app**: the web client from the backend repo, opened full screen in a Trusted Web Activity (Chrome's engine, no browser UI). Login and data live on the server; nothing is duplicated here.
- **The widget**: a native home-screen widget (Kotlin + Glance) that polls `GET /summary/daily` every 30 minutes and shows balance, today's spend and earnings, budget left, and the first target's per-day figure. Display only: it never computes money.

## Build

1. Install [Android Studio](https://developer.android.com/studio). Open this `android/` folder as a project and let it sync (first sync downloads Gradle 8.11.1 and the SDK, a few minutes).
2. On the phone: Settings → About → tap "Build number" 7 times, then Developer options → USB debugging on. Plug in, accept the prompt.
3. Press **Run**. The app installs and opens the web client.
4. Long-press the home screen → Widgets → PAM balance → drop it. Log in once in the dialog. The widget fills within a few seconds.

Point a build at a local server with `-PpamBaseUrl=http://10.0.2.2:8000` (emulator) in Studio's Gradle settings, or edit `BASE_URL` in `app/build.gradle.kts`.

## Full-screen (no Chrome bar)

Chrome shows its URL bar until the server proves it trusts this app. Get the signing certificate fingerprint of the build you run:

```bash
keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android | grep SHA256
```

Set it on the server as `ANDROID_CERT_FINGERPRINTS` (the backend serves `/.well-known/assetlinks.json` from it), reinstall the app, and the bar disappears. A release build has its own keystore and fingerprint; add both, comma-separated.

## Layout

```
app/src/main/kotlin/ie/yarodev/pam/widget/
├── Api.kt                  POST /token and GET /summary/daily over HttpURLConnection
├── Store.kt                Token, cached summary, last error: EncryptedSharedPreferences
├── RefreshWorker.kt        WorkManager job: fetch, cache, redraw; periodic every 30 min
├── PamWidget.kt            GlanceAppWidget: renders the cached summary
├── PamWidgetReceiver.kt    Schedules/cancels the refresh when the widget is added/removed
└── WidgetConfigActivity.kt Login dialog shown when the widget is placed
```

The TWA needs no Kotlin at all: it is `com.google.androidbrowserhelper.trusted.LauncherActivity` declared in the manifest with the URL as metadata.
