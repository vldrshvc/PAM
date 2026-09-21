package ie.yarodev.pam.notify

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import ie.yarodev.pam.widget.Store
import java.time.LocalDate

/**
 * Watches every notification on the device and keeps almost none of them.
 *
 * Android does not let a listener subscribe to particular apps, so this sees
 * messages, mail and everything else. That makes the filtering order the most
 * important thing in the file: a notification is dropped before it is stored,
 * queued or sent unless it looks like money. Nothing that fails the filter is
 * written anywhere, not even to the log.
 */
class PamNotificationListener : NotificationListenerService() {

    // onNotificationPosted runs on the main thread for every notification on
    // the device, and opening this is keystore work. Once per service, not
    // once per notification.
    private val store by lazy { Store(this) }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (!store.captureNotifications || !store.isConfigured) return
        if (sbn.packageName == packageName) return
        if (sbn.packageName in store.muted) return

        val notification = sbn.notification ?: return
        // Ongoing (music, navigation, downloads) and the summary row of a
        // bundle are never a payment, and the summary would duplicate its
        // children anyway.
        if (notification.flags and Notification.FLAG_ONGOING_EVENT != 0) return
        if (notification.flags and Notification.FLAG_GROUP_SUMMARY != 0) return

        val extras = notification.extras ?: return
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.trim()
        val text = (
            extras.getCharSequence(Notification.EXTRA_BIG_TEXT)
                ?: extras.getCharSequence(Notification.EXTRA_TEXT)
            )?.toString()?.trim().orEmpty()
        if (text.isEmpty()) return

        // The privacy boundary: everything above this line stays on the phone
        // unless the text has an amount in it.
        if (!MoneyFilter.couldBeMoney("$title $text")) return

        val captured = Captured(sbn.packageName, title, text)
        val queue = store.queue + captured.toJson(LocalDate.now()).toString()
        // A bounded queue: if the phone has been offline for days, the newest
        // are the ones still worth confirming.
        store.queue = queue.takeLast(MAX_QUEUED)
        Log.i(TAG, "queued a possible payment from ${sbn.packageName}")
        SendWorker.sendNow(this)
    }

    override fun onListenerConnected() {
        // A reconnect (reboot, app update, permission re-granted) is the usual
        // moment for a backlog to exist.
        SendWorker.sendNow(this)
    }

    private companion object {
        const val TAG = "PamNotifications"
        const val MAX_QUEUED = 100
    }
}
