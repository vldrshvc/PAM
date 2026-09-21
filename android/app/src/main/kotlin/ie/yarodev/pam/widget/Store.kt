package ie.yarodev.pam.widget

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import ie.yarodev.pam.BuildConfig
import org.json.JSONArray

/** Token and the last fetched summary, encrypted at rest. */
class Store(context: Context) {

    // security-crypto 1.0.0 signature: file name, key alias, context, then the
    // two schemes. The key itself lives in the Android keystore.
    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        "pam_widget",
        MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC),
        context,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    var baseUrl: String
        get() = prefs.getString(KEY_BASE_URL, null) ?: BuildConfig.BASE_URL
        set(value) = prefs.edit().putString(KEY_BASE_URL, value.trimEnd('/')).apply()

    var token: String?
        get() = prefs.getString(KEY_TOKEN, null)
        set(value) = prefs.edit().putString(KEY_TOKEN, value).apply()

    var lastSummaryJson: String?
        get() = prefs.getString(KEY_SUMMARY, null)
        set(value) = prefs.edit().putString(KEY_SUMMARY, value).apply()

    var lastUpdatedMillis: Long
        get() = prefs.getLong(KEY_UPDATED, 0L)
        set(value) = prefs.edit().putLong(KEY_UPDATED, value).apply()

    var lastError: String?
        get() = prefs.getString(KEY_ERROR, null)
        set(value) = prefs.edit().putString(KEY_ERROR, value).apply()

    val isConfigured: Boolean get() = token != null

    /** Whether the user has switched notification capture on, separately from
     *  granting Android the listener permission. Both have to be true. */
    var captureNotifications: Boolean
        get() = prefs.getBoolean(KEY_CAPTURE, false)
        set(value) = prefs.edit().putBoolean(KEY_CAPTURE, value).apply()

    /** Notifications waiting to be sent, oldest first. Kept encrypted like
     *  everything else here, because they are the user's bank messages. */
    var queue: List<String>
        get() = prefs.getString(KEY_QUEUE, null)?.let { readArray(it) } ?: emptyList()
        set(value) = prefs.edit().putString(KEY_QUEUE, JSONArray(value).toString()).apply()

    /** Apps whose notifications are not worth sending. See SendWorker. */
    var muted: Set<String>
        get() = prefs.getStringSet(KEY_MUTED, emptySet()) ?: emptySet()
        set(value) = prefs.edit().putStringSet(KEY_MUTED, value).apply()

    /** How many times in a row an app produced something the server had no
     *  use for. Reset the moment it produces something real. */
    fun ignoredCount(packageName: String): Int = prefs.getInt(KEY_IGNORED + packageName, 0)

    fun setIgnoredCount(packageName: String, count: Int) =
        prefs.edit().putInt(KEY_IGNORED + packageName, count).apply()

    fun clear() = prefs.edit().clear().apply()

    private fun readArray(raw: String): List<String> =
        runCatching {
            val array = JSONArray(raw)
            (0 until array.length()).map { array.getString(it) }
        }.getOrDefault(emptyList())

    private companion object {
        const val KEY_BASE_URL = "base_url"
        const val KEY_TOKEN = "token"
        const val KEY_SUMMARY = "summary"
        const val KEY_UPDATED = "updated"
        const val KEY_ERROR = "error"
        const val KEY_CAPTURE = "capture_notifications"
        const val KEY_QUEUE = "notification_queue"
        const val KEY_MUTED = "muted_packages"
        const val KEY_IGNORED = "ignored_"
    }
}
