package ie.yarodev.pam.notify

import android.content.ComponentName
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat
import ie.yarodev.pam.R
import ie.yarodev.pam.widget.Store

/**
 * Turning notification capture on, and seeing what it is doing.
 *
 * Two separate switches, deliberately: Android's own notification access, and
 * PAM's. Granting Android access does not start anything on its own, so the
 * permission can stay granted while the feature is off.
 */
class NotificationSetupActivity : AppCompatActivity() {

    private val store by lazy { Store(this) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_notification_setup)

        findViewById<Button>(R.id.grant_access).setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        // A click rather than a checked-change, because render() sets the
        // switch on every resume and that would fire a change listener.
        findViewById<SwitchCompat>(R.id.capture).setOnClickListener {
            val on = (it as SwitchCompat).isChecked
            store.captureNotifications = on
            if (on) SendWorker.sendNow(this)
        }
        findViewById<Button>(R.id.unmute).setOnClickListener {
            for (packageName in store.muted) store.setIgnoredCount(packageName, 0)
            store.muted = emptySet()
            render()
        }
    }

    // The user leaves for the system settings screen and comes back, so the
    // state is read again here rather than only at creation.
    override fun onResume() {
        super.onResume()
        render()
    }

    private fun render() {
        val granted = isAccessGranted()
        findViewById<TextView>(R.id.access_state).setText(
            if (granted) R.string.notify_access_on else R.string.notify_access_off
        )
        val capture = findViewById<SwitchCompat>(R.id.capture)
        capture.isChecked = store.captureNotifications
        // Nothing to send to until the widget login has happened.
        capture.isEnabled = store.isConfigured
        findViewById<TextView>(R.id.muted).text = when {
            !store.isConfigured -> getString(R.string.notify_needs_login)
            store.muted.isEmpty() -> getString(R.string.notify_muted_none)
            else -> getString(R.string.notify_muted_some, store.muted.sorted().joinToString(", "))
        }
    }

    /**
     * Whether Android is willing to give this service notifications.
     *
     * Read from the secure setting rather than kept as a flag of our own: the
     * user can revoke it in system settings at any time, and only Android
     * knows the truth.
     */
    private fun isAccessGranted(): Boolean {
        val enabled = Settings.Secure.getString(contentResolver, "enabled_notification_listeners").orEmpty()
        val mine = ComponentName(this, PamNotificationListener::class.java)
        return enabled.split(":").any {
            ComponentName.unflattenFromString(it)?.equals(mine) == true
        }
    }
}
