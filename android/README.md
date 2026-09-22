# PAM for Android

Two things in one APK:

- **The app**: the web client from the backend repo, opened full screen in a Trusted Web Activity (Chrome's engine, no browser UI). Login and data live on the server; nothing is duplicated here.
- **The widget**: a native home-screen widget (Kotlin + Glance) that polls `GET /summary/daily` every 30 minutes and shows balance, today's spend and earnings, budget left, and the first target's per-day figure. Display only: it never computes money.
- **Notification capture**: a `NotificationListenerService` that watches what banking apps post and turns payments into entries you confirm in the app.

## Build

1. Install [Android Studio](https://developer.android.com/studio). Open this `android/` folder as a project and let it sync (first sync downloads Gradle 8.11.1 and the SDK, a few minutes).
2. On the phone: Settings → About → tap "Build number" 7 times, then Developer options → USB debugging on. Plug in, accept the prompt.
3. Press **Run**. The app installs and opens the web client.
4. Long-press the home screen → Widgets → PAM balance → drop it. Log in once in the dialog. The widget fills within a few seconds.

Point a build at a local server with `-PpamBaseUrl=http://10.0.2.2:8000` (emulator) in Studio's Gradle settings, or edit `BASE_URL` in `app/build.gradle.kts`.

## Notification capture

Turn it on by long-pressing the PAM icon → **Bank notifications**, or from the
Accounts tab in the app ("Set up in the app"). Some launchers hide app
shortcuts; `adb shell am start -a android.intent.action.VIEW -d
"pam://notifications"` opens the same screen from a laptop.

Two separate switches there: Android's own notification access, and PAM's.
Granting the Android permission starts nothing on its own. If there is no
token yet the screen offers a **Log in** button, which is the same form the
widget uses — capture does not need a widget, only an account to send to.

**What leaves the phone.** Android does not let a listener subscribe to
particular apps, so this service sees every notification on the device,
messages included. `MoneyFilter.kt` is the whole privacy boundary: unless the
text has an amount with a currency next to it, the notification is dropped
before it is stored, queued, sent or even logged. The same expression lives in
`app/services/notifications.py` on the server and is applied again there — if
you change one, change both.

**What happens to what does get sent.** It becomes a *pending* expense. That
counts towards no balance, no budget and no total until you tap it to confirm
in the app. Money arriving is reported and not recorded, because an income has
a source you pick.

**Sending.** Queued in the same encrypted store as the token and drained by a
WorkManager job, so a phone with no signal keeps the backlog and sends it when
it has one. The queue is capped at 100: after days offline, the newest are the
ones still worth confirming.

**The ignored list.** The server says what it made of each notification. An app
that produces five in a row that were not payments, and never a payment, is
muted on the phone. A bank that sends balance updates as well as payments is
never muted, because its payments reset the count. Clear the list from the same
screen.

**Why a content hash for the key.** Banks reuse one notification id for every
payment, so Android's own key would make two different purchases collide. The
key is a hash of the app, the text and the day instead. The trade-off: two
identical payments on one day (same shop, same amount) collide and only the
first is kept — rare, and the second can be added by hand, where booking every
notification twice would be constant.

## Full-screen (no Chrome bar)

Chrome shows its URL bar until the server proves it trusts this app. Get the signing certificate fingerprint of the build you run:

```bash
keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android | grep SHA256
```

Set it on the server as `ANDROID_CERT_FINGERPRINTS` (the backend serves `/.well-known/assetlinks.json` from it), reinstall the app, and the bar disappears. A release build has its own keystore and fingerprint; add both, comma-separated.

## Layout

```
app/src/main/kotlin/ie/yarodev/pam/
├── notify/
│   ├── MoneyFilter.kt              The one judgement the phone makes: could this be money?
│   ├── Captured.kt                 A notification worth sending, and its dedupe key
│   ├── PamNotificationListener.kt  Sees everything, keeps almost none of it
│   ├── SendWorker.kt               Drains the queue; feeds the ignored list
│   └── NotificationSetupActivity.kt  Turning it on, and seeing what it is doing
└── widget/
    ├── Api.kt                  POST /token, POST /notifications, GET /summary/daily
    ├── Store.kt                Token, cached summary, queue, ignored list: EncryptedSharedPreferences
    ├── RefreshWorker.kt        WorkManager job: fetch, cache, redraw; periodic every 30 min
    ├── PamWidget.kt            GlanceAppWidget: renders the cached summary
    ├── PamWidgetReceiver.kt    Schedules/cancels the refresh when the widget is added/removed
    └── WidgetConfigActivity.kt Login dialog shown when the widget is placed
```

The TWA needs no Kotlin at all: it is `com.google.androidbrowserhelper.trusted.LauncherActivity` declared in the manifest with the URL as metadata.
