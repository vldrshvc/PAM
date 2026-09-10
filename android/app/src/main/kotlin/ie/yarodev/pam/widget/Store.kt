package ie.yarodev.pam.widget

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import ie.yarodev.pam.BuildConfig

/** Token and the last fetched summary, encrypted at rest. */
class Store(context: Context) {

    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        context,
        "pam_widget",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
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

    fun clear() = prefs.edit().clear().apply()

    private companion object {
        const val KEY_BASE_URL = "base_url"
        const val KEY_TOKEN = "token"
        const val KEY_SUMMARY = "summary"
        const val KEY_UPDATED = "updated"
        const val KEY_ERROR = "error"
    }
}
