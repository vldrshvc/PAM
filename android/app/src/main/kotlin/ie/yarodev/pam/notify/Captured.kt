package ie.yarodev.pam.notify

import org.json.JSONObject
import java.security.MessageDigest
import java.time.LocalDate

/**
 * One notification worth sending, and the key that stops it being sent twice.
 *
 * The key is a hash of the app, the text and the day rather than Android's own
 * notification key, because banks reuse a notification id for every payment:
 * two different purchases would share a key and the second would be dropped.
 * Hashing the content is the other trade-off — two identical payments in one
 * day (same shop, same amount) collide and only the first is kept. That is
 * rare and the user can add the second by hand; booking every notification
 * twice would be constant.
 */
data class Captured(
    val packageName: String,
    val title: String?,
    val text: String,
) {
    fun key(today: LocalDate): String = sha256("$packageName|${title.orEmpty()}|$text|$today").take(32)

    fun toJson(today: LocalDate): JSONObject = JSONObject()
        .put("key", key(today))
        .put("package", packageName)
        .put("text", text)
        .apply { if (!title.isNullOrBlank()) put("title", title) }

    companion object {
        fun fromJson(json: JSONObject): Captured = Captured(
            packageName = json.getString("package"),
            title = json.optString("title").ifBlank { null },
            text = json.getString("text"),
        )

        private fun sha256(value: String): String =
            MessageDigest.getInstance("SHA-256")
                .digest(value.toByteArray())
                .joinToString("") { "%02x".format(it) }
    }
}
