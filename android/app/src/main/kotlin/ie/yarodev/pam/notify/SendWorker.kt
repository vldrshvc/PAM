package ie.yarodev.pam.notify

import android.content.Context
import android.util.Log
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import ie.yarodev.pam.widget.Api
import ie.yarodev.pam.widget.RefreshWorker
import ie.yarodev.pam.widget.Store
import org.json.JSONObject
import java.util.TimeZone

/**
 * Drains the queue of captured notifications to the server.
 *
 * Runs through WorkManager rather than from the listener directly so that a
 * phone with no signal keeps the backlog and sends it when it has one. Each
 * notification is posted on its own: the server is what decides whether it was
 * a payment, and one bad item must not block the rest.
 *
 * It also feeds the mute list. The server answers every post with an outcome,
 * and an app that produces MUTE_AFTER useless ones in a row without ever
 * producing a payment is muted on the phone. A bank that sends balance updates
 * as well as payments is never muted, because its payments reset the count.
 */
class SendWorker(context: Context, params: WorkerParameters) : Worker(context, params) {

    override fun doWork(): Result {
        val store = Store(applicationContext)
        val token = store.token ?: return Result.success()
        if (!store.captureNotifications) return Result.success()

        val pending = store.queue
        if (pending.isEmpty()) return Result.success()

        val timezone = TimeZone.getDefault().id
        val unsent = mutableListOf<String>()
        var booked = false
        for (raw in pending) {
            val captured = runCatching { Captured.fromJson(JSONObject(raw)) }.getOrNull()
            if (captured == null) continue          // unreadable: drop it, not worth a retry
            if (captured.packageName in store.muted) continue
            val answer = runCatching {
                Api.postNotification(store.baseUrl, token, JSONObject(raw), timezone)
            }
            answer.onSuccess { response ->
                val outcome = response.optString("outcome")
                if (outcome == "pending") booked = true
                remember(store, captured.packageName, outcome)
            }.onFailure { error ->
                // A rejection is final; only a network or server failure is
                // worth keeping, and only that comes back as a retry.
                if (error is Api.ApiException) {
                    Log.w(TAG, "server refused a notification: ${error.message}")
                } else {
                    unsent += raw
                }
            }
        }
        store.queue = unsent
        // A new pending expense changes nothing on the widget yet, but the
        // user is about to open the app; a fresh summary costs one request.
        if (booked) RefreshWorker.refreshNow(applicationContext)
        return if (unsent.isEmpty()) Result.success() else Result.retry()
    }

    /** Count what the server made of this app, and mute the hopeless ones. */
    private fun remember(store: Store, packageName: String, outcome: String) {
        if (outcome == "pending" || outcome == "duplicate" || outcome == "incoming") {
            store.setIgnoredCount(packageName, 0)
            return
        }
        val count = store.ignoredCount(packageName) + 1
        store.setIgnoredCount(packageName, count)
        if (count >= MUTE_AFTER) {
            store.muted = store.muted + packageName
            Log.i(TAG, "muted $packageName after $count notifications the server had no use for")
        }
    }

    companion object {
        private const val TAG = "PamNotifications"
        private const val WORK_NAME = "pam-send-notifications"

        /** How many useless notifications in a row before an app is muted. */
        const val MUTE_AFTER = 5

        fun sendNow(context: Context) {
            val request = OneTimeWorkRequestBuilder<SendWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            // APPEND_OR_REPLACE: a burst of notifications should not start a
            // run each, but one arriving mid-run must not be forgotten.
            WorkManager.getInstance(context)
                .enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
        }
    }
}
