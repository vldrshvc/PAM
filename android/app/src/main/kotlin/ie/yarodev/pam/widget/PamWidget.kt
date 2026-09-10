package ie.yarodev.pam.widget

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.provideContent
import androidx.glance.background
import androidx.glance.layout.Alignment
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.width
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import androidx.glance.unit.ColorProvider
import com.google.androidbrowserhelper.trusted.LauncherActivity
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Display only. Everything shown comes straight from GET /summary/daily; the
 * widget never computes money itself.
 */
class PamWidget : GlanceAppWidget() {

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val store = Store(context)
        val summary = store.lastSummaryJson?.let { runCatching { JSONObject(it) }.getOrNull() }
        val state = WidgetState(
            configured = store.isConfigured,
            summary = summary,
            updatedAt = store.lastUpdatedMillis,
            error = store.lastError,
        )
        provideContent { Content(state) }
    }
}

private data class WidgetState(
    val configured: Boolean,
    val summary: JSONObject?,
    val updatedAt: Long,
    val error: String?,
)

private val green = ColorProvider(Color(0xFF1F6F5F))
private val ink = ColorProvider(Color(0xFF1B1F1E))
private val muted = ColorProvider(Color(0xFF6B7371))
private val danger = ColorProvider(Color(0xFFB8322F))
private val card = ColorProvider(Color(0xFFFFFFFF))

@Composable
private fun Content(state: WidgetState) {
    val openApp = actionStartActivity<LauncherActivity>()
    val setUp = actionStartActivity<WidgetConfigActivity>()

    Column(
        modifier = GlanceModifier.fillMaxSize().background(card).cornerRadius(16.dp).padding(14.dp)
            .clickable(if (state.configured) openApp else setUp),
    ) {
        when {
            !state.configured -> Message("PAM", "Tap to connect the widget", muted)
            state.summary == null -> Message("PAM", state.error ?: "Loading…", muted)
            else -> Summary(state.summary, state.updatedAt, state.error)
        }
    }
}

@Composable
private fun Message(title: String, body: String, color: ColorProvider) {
    Text(title, style = TextStyle(color = green, fontWeight = FontWeight.Bold, fontSize = 14.sp))
    Spacer(GlanceModifier.height(6.dp))
    Text(body, style = TextStyle(color = color, fontSize = 14.sp))
}

@Composable
private fun Summary(summary: JSONObject, updatedAt: Long, error: String?) {
    Row(modifier = GlanceModifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text("BALANCE", style = TextStyle(color = muted, fontSize = 11.sp, fontWeight = FontWeight.Medium))
        Spacer(GlanceModifier.width(8.dp))
        Text(
            if (error != null) "offline · " + timeOf(updatedAt) else timeOf(updatedAt),
            style = TextStyle(color = if (error != null) danger else muted, fontSize = 11.sp),
        )
    }
    Text(euro(summary.optString("balance")), style = TextStyle(color = ink, fontSize = 30.sp, fontWeight = FontWeight.Bold))
    Spacer(GlanceModifier.height(6.dp))
    Row(modifier = GlanceModifier.fillMaxWidth()) {
        Stat("Spent today", euro(summary.optString("spent_today")), ink)
        Spacer(GlanceModifier.width(18.dp))
        Stat("Earned today", "+" + euro(summary.optString("earned_today")), green)
        Spacer(GlanceModifier.width(18.dp))
        val overBudget = summary.optBoolean("over_budget")
        val budgetTotal = summary.optString("budget_total")
        if (budgetTotal != "0.00") {
            Stat("Budget left", euro(summary.optString("remaining_total")), if (overBudget) danger else ink)
        }
    }
    val target = summary.optJSONArray("targets")?.let { if (it.length() > 0) it.getJSONObject(0) else null }
    if (target != null) {
        Spacer(GlanceModifier.height(6.dp))
        Text(targetLine(target), style = TextStyle(color = if (target.optString("status") == "behind") danger else muted, fontSize = 12.sp))
    }
}

@Composable
private fun Stat(label: String, value: String, color: ColorProvider) {
    Column {
        Text(label, style = TextStyle(color = muted, fontSize = 10.sp))
        Text(value, style = TextStyle(color = color, fontSize = 15.sp, fontWeight = FontWeight.Bold))
    }
}

private fun targetLine(target: JSONObject): String {
    val name = target.optString("name")
    return when (target.optString("status")) {
        "achieved" -> "$name: reached"
        "expired" -> "$name: missed by ${euro(target.optString("remaining"))}"
        else -> "$name: ${euro(target.optString("required_per_day"))}/day · ${target.optInt("days_left")} days left"
    }
}

private fun euro(value: String): String = if (value.isEmpty()) "–" else "€$value"

private fun timeOf(millis: Long): String =
    if (millis == 0L) "" else SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(millis))
