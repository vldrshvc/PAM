package ie.yarodev.pam.widget

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** The two calls the widget needs. Plain HttpURLConnection: no extra dependency for two requests. */
object Api {

    class ApiException(message: String) : IOException(message)

    fun login(baseUrl: String, username: String, password: String): String {
        val body = "username=${encode(username)}&password=${encode(password)}"
        val json = request("$baseUrl/token", "POST", body, "application/x-www-form-urlencoded", token = null)
        return json.getString("access_token")
    }

    fun dailySummary(baseUrl: String, token: String, timezone: String): JSONObject =
        request("$baseUrl/summary/daily?tz=${encode(timezone)}", "GET", body = null, contentType = null, token = token)

    private fun request(url: String, method: String, body: String?, contentType: String?, token: String?): JSONObject {
        val connection = URL(url).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            // Render's free tier can take a minute to wake; be patient once.
            connection.connectTimeout = 20_000
            connection.readTimeout = 60_000
            connection.setRequestProperty("Accept", "application/json")
            if (token != null) connection.setRequestProperty("Authorization", "Bearer $token")
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", contentType)
                connection.outputStream.use { it.write(body.toByteArray()) }
            }
            val status = connection.responseCode
            val stream = if (status < 400) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
            if (status >= 400) throw ApiException(describe(status, text))
            return JSONObject(text)
        } finally {
            connection.disconnect()
        }
    }

    private fun describe(status: Int, text: String): String {
        val detail = runCatching { JSONObject(text).opt("detail") }.getOrNull()
        return when (detail) {
            is String -> detail
            else -> "HTTP $status"
        }
    }

    private fun encode(value: String): String = URLEncoder.encode(value, "UTF-8")
}
