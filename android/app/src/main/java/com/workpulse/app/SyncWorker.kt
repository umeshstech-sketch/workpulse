package com.workpulse.app

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import java.io.IOException
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.util.concurrent.TimeUnit

/**
 * Every 15 minutes (Android's minimum): send this phone's usage to the laptop, over home Wi-Fi or, when you're
 * out, Tailscale (whichever address answers). Re-sending a day replaces it on the laptop, so this is safe to
 * repeat. If the laptop can't be reached, nothing is lost: Android keeps the usage history, and the next
 * successful sync sends every day since the last one (up to a week).
 */
class SyncWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val prefs = Prefs(applicationContext)
        val token = prefs.token
        if (!prefs.isPaired || token == null) return@withContext Result.success()
        if (!UsageCollector.hasUsageAccess(applicationContext)) {
            prefs.lastError = "Usage access not allowed"
            return@withContext Result.success()
        }
        val host = Api.findHost(prefs)
        if (host == null) {
            prefs.lastError = "Laptop not reachable (laptop asleep, or you're out and away access / Tailscale is off)"
            return@withContext Result.retry()
        }
        val name = prefs.deviceName ?: android.os.Build.MODEL
        try {
            val payload = JSONArray()
            for (day in daysToSend(prefs.lastSync)) payload.put(Tracker.laptopPayload(applicationContext, day, name))
            Api.request("http://$host", "/api/phone/ingest", "POST", payload.toString(), token)
            prefs.lastSync = System.currentTimeMillis()
            prefs.lastError = null
            Api.refreshHosts(prefs, host, token)
            Result.success()
        } catch (e: Api.HttpError) {
            prefs.lastError = if (e.code == 401) "This phone was removed on the laptop: pair again" else e.message
            Result.success()  // retrying won't fix a rejected token
        } catch (e: IOException) {
            prefs.lastError = "Connection to the laptop dropped; will retry"
            Result.retry()
        }
    }

    companion object {
        private const val PERIODIC = "workpulse-sync"
        private const val NOW = "workpulse-sync-now"
        private const val MAX_CATCH_UP_DAYS = 7L

        /** The day before the last successful sync (it may have ended mid-day) through today; at most a week. */
        fun daysToSend(lastSync: Long, today: LocalDate = LocalDate.now()): List<LocalDate> {
            val lastDay = if (lastSync > 0) Instant.ofEpochMilli(lastSync).atZone(ZoneId.systemDefault()).toLocalDate() else today
            var from = minOf(lastDay, today).minusDays(1)
            if (from.isBefore(today.minusDays(MAX_CATCH_UP_DAYS - 1))) from = today.minusDays(MAX_CATCH_UP_DAYS - 1)
            return generateSequence(from) { it.plusDays(1) }.takeWhile { !it.isAfter(today) }.toList()
        }

        fun schedule(context: Context) {
            val req = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.KEEP, req)
        }

        fun syncNow(context: Context) {
            WorkManager.getInstance(context).enqueueUniqueWork(NOW, ExistingWorkPolicy.REPLACE, OneTimeWorkRequestBuilder<SyncWorker>().build())
        }

        fun cancel(context: Context) {
            WorkManager.getInstance(context).cancelUniqueWork(PERIODIC)
        }
    }
}
