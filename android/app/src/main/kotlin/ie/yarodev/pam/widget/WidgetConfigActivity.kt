package ie.yarodev.pam.widget

import android.appwidget.AppWidgetManager
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import ie.yarodev.pam.R
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Widget login. Exchanges username + password for a token once, stores it
 * encrypted, and never keeps the password.
 */
class WidgetConfigActivity : AppCompatActivity() {

    private var appWidgetId = AppWidgetManager.INVALID_APPWIDGET_ID

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_widget_config)

        appWidgetId = intent?.extras?.getInt(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
            ?: AppWidgetManager.INVALID_APPWIDGET_ID
        // Until login succeeds the host treats the placement as cancelled.
        setResult(RESULT_CANCELED)

        val store = Store(this)
        val serverUrl = findViewById<EditText>(R.id.server_url).apply { setText(store.baseUrl) }
        val username = findViewById<EditText>(R.id.username)
        val password = findViewById<EditText>(R.id.password)
        val error = findViewById<TextView>(R.id.error)
        val connect = findViewById<Button>(R.id.connect)

        connect.setOnClickListener {
            val url = serverUrl.text.toString().trim().trimEnd('/')
            val user = username.text.toString().trim()
            val pass = password.text.toString()
            if (url.isEmpty() || user.isEmpty() || pass.isEmpty()) return@setOnClickListener
            connect.isEnabled = false
            connect.setText(R.string.connecting)
            error.visibility = View.GONE
            lifecycleScope.launch {
                val result = withContext(Dispatchers.IO) { runCatching { Api.login(url, user, pass) } }
                result.onSuccess { token ->
                    store.baseUrl = url
                    store.token = token
                    store.lastError = null
                    RefreshWorker.schedule(this@WidgetConfigActivity)
                    RefreshWorker.refreshNow(this@WidgetConfigActivity)
                    finishWithResult()
                }.onFailure { e ->
                    error.text = getString(R.string.login_failed, e.message ?: e.javaClass.simpleName)
                    error.visibility = View.VISIBLE
                    connect.isEnabled = true
                    connect.setText(R.string.connect)
                }
            }
        }
    }

    private fun finishWithResult() {
        if (appWidgetId != AppWidgetManager.INVALID_APPWIDGET_ID) {
            setResult(RESULT_OK, Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, appWidgetId))
        }
        finish()
    }
}
