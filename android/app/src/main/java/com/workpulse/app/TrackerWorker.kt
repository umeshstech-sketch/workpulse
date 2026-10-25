package com.workpulse.app

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.LocalTime
import java.util.concurrent.TimeUnit

/**
 * Every 15 minutes (Android's minimum), on the phone itself: save today's usage (and finish yesterday's), then
 * check your app limits, daily goal and bedtime. Each reminder is sent at most once per day.
 */
class TrackerWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val ctx = applicationContext
        if (!UsageCollector.hasUsageAccess(ctx)) return@withContext Result.success()
        val store = Store(ctx)
        val today = LocalDate.now()
        Tracker.get(ctx, today.minusDays(1), store)  // finishes yesterday after midnight (no-op once saved)
        val settings = store.settings()
        val day = Tracker.forUi(Tracker.get(ctx, today, store), settings)
        if (settings.optBoolean("notifyLimits", true)) checkLimits(ctx, store, today, day, settings)
        if (settings.optBoolean("bedtimeReminder", true)) checkBedtime(ctx, store, day, settings)
        // A focus session whose end alarm was delayed: finish it here and still tell you.
        Focus.state(ctx, store).optJSONObject("just_finished")?.let { s ->
            Notifier.show(ctx, 1003, Notifier.FOCUS, "${s.optString("label").ifEmpty { "Focus" }} done: ${s.optInt("planned_min")} min ✅",
                Focus.report(s), view = "focus")
        }
        Result.success()
    }

    private fun checkLimits(ctx: Context, store: Store, today: LocalDate, day: org.json.JSONObject, settings: org.json.JSONObject) {
        val limits = settings.optJSONObject("limits") ?: return
        val apps = day.optJSONArray("apps")
        for (pkg in limits.keys()) {
            val limitS = limits.optInt(pkg) * 60L
            if (limitS <= 0 || apps == null) continue
            val app = (0 until apps.length()).map { apps.getJSONObject(it) }.firstOrNull { it.getString("pkg") == pkg } ?: continue
            val used = app.optLong("s")
            val name = app.getString("name")
            if (used >= limitS && store.flagOnce(today, "limit:$pkg:100")) {
                Notifier.show(ctx, pkg.hashCode(), Notifier.LIMITS, "$name limit reached",
                    "You've used $name for ${fmt(used)} today (your limit is ${fmt(limitS)}). Time for something else?")
            } else if (used in (limitS * 8 / 10) until limitS && store.flagOnce(today, "limit:$pkg:80")) {
                Notifier.show(ctx, pkg.hashCode(), Notifier.LIMITS, "$name: ${fmt(limitS - used)} left",
                    "${fmt(used)} of your ${fmt(limitS)} daily limit used.")
            }
        }
        val goalS = settings.optInt("dailyGoalMin", 0) * 60L
        if (goalS > 0 && day.optLong("total_s") >= goalS && store.flagOnce(today, "goal")) {
            Notifier.show(ctx, 1001, Notifier.LIMITS, "Daily screen-time goal reached",
                "${fmt(day.optLong("total_s"))} on your phone today; your goal was ${fmt(goalS)}.")
        }
    }

    private fun checkBedtime(ctx: Context, store: Store, day: org.json.JSONObject, settings: org.json.JSONObject) {
        val bed = parse(settings.optString("bedtime")) ?: return
        val wake = parse(settings.optString("wake")) ?: return
        val now = LocalTime.now()
        val night = if (bed < wake) now >= bed && now < wake else now >= bed || now < wake
        if (!night) return
        val lastUse = day.optLong("last_use", 0L)
        if (System.currentTimeMillis() - lastUse > 16 * 60_000L) return  // not using the phone right now
        val nightOf = if (now < wake) LocalDate.now().minusDays(1) else LocalDate.now()
        if (store.flagOnce(nightOf, "bedtime")) {
            Notifier.show(ctx, 1002, Notifier.BEDTIME, "It's past your bedtime",
                "You planned to stop at ${settings.optString("bedtime")}. Put the phone down and get some rest. 🌙")
        }
    }

    companion object {
        private const val PERIODIC = "workpulse-track"

        fun parse(hhmm: String): LocalTime? = runCatching { LocalTime.parse(hhmm) }.getOrNull()

        fun fmt(s: Long): String {
            val m = (s + 30) / 60
            return if (m >= 60) "${m / 60}h ${m % 60}m" else "${m}m"
        }

        fun schedule(context: Context) {
            val req = PeriodicWorkRequestBuilder<TrackerWorker>(15, TimeUnit.MINUTES).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.KEEP, req)
        }
    }
}
