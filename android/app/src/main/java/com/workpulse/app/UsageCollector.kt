package com.workpulse.app

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Build
import android.os.Process

/**
 * Reads Android's usage events: which app was in front, from when to when, and phone unlocks.
 * Only app names and durations: Android's usage stats never contain what's on screen or typed.
 */
object UsageCollector {
    // UsageEvents.Event constants (numeric so they work on every supported API level)
    private const val RESUMED = 1          // ACTIVITY_RESUMED / MOVE_TO_FOREGROUND
    private const val PAUSED = 2           // ACTIVITY_PAUSED / MOVE_TO_BACKGROUND
    private const val SCREEN_ON = 15       // SCREEN_INTERACTIVE
    private const val SCREEN_OFF = 16      // SCREEN_NON_INTERACTIVE
    private const val KEYGUARD_HIDDEN = 18 // phone unlocked ("pickup"), API 28+
    private const val STOPPED = 23         // ACTIVITY_STOPPED, API 29+
    private const val HOUR = 3_600_000L

    class AppUse(val pkg: String) {
        var ms = 0L
        var opens = 0
    }

    /** Everything WorkPulse knows about a time window. `hourly` is per hour from `start` (meaningful for whole days). */
    class Analysis(
        val apps: Map<String, AppUse>,
        val hourly: LongArray,
        val pickups: Int,
        val firstPickup: Long?,
        val lastUse: Long?,
        val longestMs: Long,
        val longestPkg: String?,
    )

    fun hasUsageAccess(context: Context): Boolean {
        val ops = context.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName)
        } else {
            @Suppress("DEPRECATION")
            ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName)
        }
        return mode == AppOpsManager.MODE_ALLOWED
    }

    /** Home screens and system UI: time there isn't "using an app". */
    private fun skipped(context: Context): Set<String> {
        val home = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
        return context.packageManager.queryIntentActivities(home, 0).map { it.activityInfo.packageName }.toSet() +
            setOf("android", "com.android.systemui", context.packageName)
    }

    /** Android's own category for the app (lets games/video/social apps be sorted without a keyword rule). */
    fun categoryHint(pm: PackageManager, pkg: String): String? = try {
        val ai = pm.getApplicationInfo(pkg, 0)
        when (ai.category) {
            ApplicationInfo.CATEGORY_GAME -> "game"
            ApplicationInfo.CATEGORY_AUDIO -> "audio"
            ApplicationInfo.CATEGORY_VIDEO -> "video"
            ApplicationInfo.CATEGORY_IMAGE -> "image"
            ApplicationInfo.CATEGORY_SOCIAL -> "social"
            ApplicationInfo.CATEGORY_NEWS -> "news"
            ApplicationInfo.CATEGORY_MAPS -> "maps"
            ApplicationInfo.CATEGORY_PRODUCTIVITY -> "productivity"
            else -> @Suppress("DEPRECATION") if (ai.flags and ApplicationInfo.FLAG_IS_GAME != 0) "game" else null
        }
    } catch (e: PackageManager.NameNotFoundException) {
        null
    }

    fun label(pm: PackageManager, pkg: String): String = try {
        pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
    } catch (e: PackageManager.NameNotFoundException) {
        pkg.substringAfterLast('.').replaceFirstChar { it.uppercase() }
    }

    fun analyze(context: Context, start: Long, end: Long): Analysis {
        val usm = context.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val events = usm.queryEvents(start, end)
        val ev = UsageEvents.Event()
        val skip = skipped(context)
        val apps = HashMap<String, AppUse>()
        val hourly = LongArray(24)
        var current: String? = null      // app in front right now
        var currentClass: String? = null // ...and which of its screens
        var since = 0L
        var lastFront: String? = null    // to count "opens" (switching to an app), not screen changes inside it
        var pickups = 0
        var screenOns = 0
        var firstPickup: Long? = null
        var firstScreenOn: Long? = null
        var lastUse: Long? = null
        var longest = 0L
        var longestPkg: String? = null
        val morning = start + 4 * HOUR   // "first pickup" ignores late-night use after midnight

        fun addHours(a: Long, b: Long) {
            var t = a
            while (t < b) {
                val h = ((t - start) / HOUR).toInt()
                val e = minOf(b, start + (h + 1) * HOUR)
                if (h in 0..23) hourly[h] += e - t
                t = e
            }
        }

        fun close(at: Long) {
            val pkg = current ?: return
            current = null
            currentClass = null
            if (pkg in skip) return
            val ms = (at - since).coerceAtLeast(0L)
            apps.getOrPut(pkg) { AppUse(pkg) }.ms += ms
            addHours(since, at)
            lastUse = at
            if (ms > longest) { longest = ms; longestPkg = pkg }
        }

        while (events.hasNextEvent()) {
            events.getNextEvent(ev)
            val t = ev.timeStamp
            when (ev.eventType) {
                RESUMED -> {
                    if (current == ev.packageName) {
                        currentClass = ev.className  // another screen of the same app: keep counting
                    } else {
                        close(t)  // only one app is in front at a time
                        current = ev.packageName
                        currentClass = ev.className
                        since = t
                        if (ev.packageName != lastFront && ev.packageName !in skip) apps.getOrPut(ev.packageName) { AppUse(ev.packageName) }.opens++
                        lastFront = ev.packageName
                    }
                }
                PAUSED, STOPPED -> if (current == ev.packageName && (ev.className == null || ev.className == currentClass)) close(t)
                SCREEN_OFF -> { close(t); lastFront = null }
                SCREEN_ON -> { screenOns++; if (firstScreenOn == null && t >= morning) firstScreenOn = t }
                KEYGUARD_HIDDEN -> { pickups++; if (firstPickup == null && t >= morning) firstPickup = t }
            }
        }
        close(end)  // still open right now
        // "Pickups" = unlocks. Phones without a secure lock screen (or some OEM builds) don't report unlock events,
        // so fall back to screen-ons there. Either way it's an approximation.
        val usePickups = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && pickups > 0
        return Analysis(apps, hourly, if (usePickups) pickups else screenOns, if (usePickups) firstPickup else firstScreenOn,
            lastUse, longest, longestPkg)
    }
}
