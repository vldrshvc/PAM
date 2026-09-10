package ie.yarodev.pam.widget

import android.content.Context
import androidx.glance.appwidget.updateAll
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.TimeZone
import java.util.concurrent.TimeUnit

/** Fetches /summary/daily, caches it, and redraws every placed widget. */
class RefreshWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val store = Store(applicationContext)
        val token = store.token ?: return Result.success()
        try {
            val summary = Api.dailySummary(store.baseUrl, token, TimeZone.getDefault().id)
            store.lastSummaryJson = summary.toString()
            store.lastUpdatedMillis = System.currentTimeMillis()
            store.lastError = null
        } catch (e: Api.ApiException) {
            // A 401 means the token is gone (expired, secret rotated): ask for login again.
            if (e.message?.contains("Not authenticated") == true || e.message?.contains("Token") == true) store.token = null
            store.lastError = e.message
        } catch (e: Exception) {
            store.lastError = e.message ?: e.javaClass.simpleName
        }
        PamWidget().updateAll(applicationContext)
        return if (store.lastError == null) Result.success() else Result.retry()
    }

    companion object {
        private const val PERIODIC = "pam-widget-refresh"
        private const val ONCE = "pam-widget-refresh-now"

        private val online = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

        fun schedule(context: Context) {
            // 30 minutes is Android's minimum for periodic work; it also keeps the
            // Render free instance awake, within its 750 free hours a month.
            val request = PeriodicWorkRequestBuilder<RefreshWorker>(30, TimeUnit.MINUTES)
                .setConstraints(online)
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.UPDATE, request)
        }

        fun refreshNow(context: Context) {
            val request = OneTimeWorkRequestBuilder<RefreshWorker>().setConstraints(online).build()
            WorkManager.getInstance(context).enqueueUniqueWork(ONCE, ExistingWorkPolicy.REPLACE, request)
        }

        fun cancel(context: Context) {
            WorkManager.getInstance(context).cancelUniqueWork(PERIODIC)
        }
    }
}
