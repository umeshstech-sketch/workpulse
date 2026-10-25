package com.workpulse.app

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Focus timer. When a session ends, WorkPulse looks at which distracting apps you opened during it (from the
 * same usage events) and tells you, so "did I actually focus?" has an honest answer.
 */
object Focus {
    private const val ACTIVE = "focus_active"
    private const val SESSIONS = "focus_sessions"
    private const val WORK = "workpulse-focus-end"

    fun start(context: Context, minutes: Int, label: String): JSONObject {
        val store = Store(context)
        state(context, store)
        val now = System.currentTimeMillis()
        val active = JSONObject().put("start", now).put("end", now + minutes * 60_000L).put("minutes", minutes).put("label", label.take(60))
        store.setData(ACTIVE, active.toString())
        val req = OneTimeWorkRequestBuilder<FocusEndWorker>().setInitialDelay(minutes.toLong(), TimeUnit.MINUTES).build()
        WorkManager.getInstance(context).enqueueUniqueWork(WORK, ExistingWorkPolicy.REPLACE, req)
        return active
    }

    /** Stop early (or finish on time). Returns the saved session with its distraction report. */
    fun finish(context: Context, store: Store, completed: Boolean): JSONObject? {
        val active = store.getData(ACTIVE)?.let { JSONObject(it) } ?: return null
        store.setData(ACTIVE, null)
        if (!completed) WorkManager.getInstance(context).cancelUniqueWork(WORK)
        val start = active.getLong("start")
        val end = if (completed) active.getLong("end") else minOf(System.currentTimeMillis(), active.getLong("end"))
        val settings = store.settings()
        val distractingCats = settings.optJSONArray("distracting")?.let { a -> (0 until a.length()).map { a.getString(it) }.toSet() }.orEmpty()
        val keywords = settings.optJSONArray("privateKeywords")
        val overrides = settings.optJSONObject("categoryOverrides")
        val pm = context.packageManager
        val distractions = JSONArray()
        var distractingS = 0L
        if (UsageCollector.hasUsageAccess(context) && end > start) {
            UsageCollector.analyze(context, start, end).apps.values.sortedByDescending { it.ms }.forEach { u ->
                val name = UsageCollector.label(pm, u.pkg)
                if (Categorize.isPrivate(u.pkg, name, keywords)) return@forEach
                val cat = Categorize.of(u.pkg, name, UsageCollector.categoryHint(pm, u.pkg), overrides)
                if (cat in distractingCats && (u.ms >= 5_000 || u.opens > 0)) {
                    distractingS += u.ms
                    distractions.put(JSONObject().put("name", name).put("cat", cat).put("s", u.ms / 1000).put("opens", u.opens))
                }
            }
        }
        val session = JSONObject().put("start", start).put("end", end).put("planned_min", active.optInt("minutes"))
            .put("label", active.optString("label")).put("completed", completed).put("distractions", distractions)
            .put("distracting_s", distractingS / 1000)
        val sessions = store.list(SESSIONS)
        sessions.put(session)
        val keep = JSONArray()
        for (i in maxOf(0, sessions.length() - 300) until sessions.length()) keep.put(sessions.get(i))
        store.setData(SESSIONS, keep.toString())
        return session
    }

    /** Current timer (if any) and past sessions. Finishes a session whose time is up. */
    fun state(context: Context, store: Store = Store(context)): JSONObject {
        var active = store.getData(ACTIVE)?.let { JSONObject(it) }
        var justFinished: JSONObject? = null
        if (active != null && System.currentTimeMillis() >= active.getLong("end")) {
            justFinished = finish(context, store, completed = true)
            active = null
        }
        return JSONObject().put("active", active ?: JSONObject.NULL).put("sessions", store.list(SESSIONS))
            .put("just_finished", justFinished ?: JSONObject.NULL).put("now", System.currentTimeMillis())
    }

    fun report(session: JSONObject): String {
        val d = session.optJSONArray("distractions") ?: JSONArray()
        if (d.length() == 0) return "No distracting apps opened. Great focus! 🎯"
        val parts = (0 until minOf(3, d.length())).map { d.getJSONObject(it) }.map { "${it.getString("name")} (${it.optInt("opens")}×)" }
        return "Distractions: ${parts.joinToString(", ")}, ${TrackerWorker.fmt(session.optLong("distracting_s"))} in total."
    }
}

class FocusEndWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val store = Store(applicationContext)
        val session = Focus.finish(applicationContext, store, completed = true) ?: return Result.success()
        val label = session.optString("label").ifEmpty { "Focus" }
        Notifier.show(applicationContext, 1003, Notifier.FOCUS, "$label done: ${session.optInt("planned_min")} min ✅",
            Focus.report(session), view = "focus")
        return Result.success()
    }
}
