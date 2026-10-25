package com.workpulse.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.ZoneId

/** Turns usage events into day summaries, stores them, and serves them (with categories) to the screens. */
object Tracker {
    /** Android keeps detailed usage events for roughly a week; older days come from what we saved. */
    const val EVENT_DAYS = 9L
    private const val MIN_LISTED_MS = 10_000L

    private fun bounds(day: LocalDate): Pair<Long, Long> {
        val zone = ZoneId.systemDefault()
        return day.atStartOfDay(zone).toInstant().toEpochMilli() to day.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli()
    }

    fun empty(day: LocalDate): JSONObject = JSONObject().put("day", day.toString()).put("total_s", 0).put("pickups", 0)
        .put("hourly", JSONArray(List(24) { 0 })).put("apps", JSONArray())

    /** Read a day from Android's usage events. Private apps are merged into one "Private apps" entry right here. */
    fun compute(context: Context, day: LocalDate, settings: JSONObject): JSONObject {
        val (start, dayEnd) = bounds(day)
        val now = System.currentTimeMillis()
        val a = UsageCollector.analyze(context, start, minOf(dayEnd, now))
        val pm = context.packageManager
        val keywords = settings.optJSONArray("privateKeywords")
        val merged = LinkedHashMap<String, JSONObject>()
        var total = 0L
        a.apps.values.sortedByDescending { it.ms }.forEach { u ->
            total += u.ms
            val name = UsageCollector.label(pm, u.pkg)
            val private = Categorize.isPrivate(u.pkg, name, keywords)
            val key = if (private) Categorize.PRIVATE_KEY else u.pkg
            val o = merged.getOrPut(key) {
                JSONObject().put("pkg", key).put("name", if (private) Categorize.PRIVATE_NAME else name).put("ms", 0L).put("opens", 0).also {
                    if (!private) UsageCollector.categoryHint(pm, u.pkg)?.let { h -> it.put("hint", h) }
                }
            }
            o.put("ms", o.getLong("ms") + u.ms).put("opens", o.getInt("opens") + u.opens)
        }
        val apps = JSONArray()
        merged.values.filter { it.getLong("ms") >= MIN_LISTED_MS || it.getInt("opens") >= 3 }.sortedByDescending { it.getLong("ms") }.forEach {
            apps.put(JSONObject().put("pkg", it.getString("pkg")).put("name", it.getString("name")).put("s", it.getLong("ms") / 1000)
                .put("opens", it.getInt("opens")).apply { it.optString("hint").takeIf { h -> h.isNotEmpty() }?.let { h -> put("hint", h) } })
        }
        val longest = a.longestPkg?.let { pkg ->
            val name = UsageCollector.label(pm, pkg)
            val private = Categorize.isPrivate(pkg, name, keywords)
            JSONObject().put("s", a.longestMs / 1000).put("pkg", if (private) Categorize.PRIVATE_KEY else pkg)
                .put("name", if (private) "a private app" else name)
        }
        return JSONObject().put("day", day.toString()).put("total_s", total / 1000).put("pickups", a.pickups)
            .put("first_pickup", a.firstPickup ?: JSONObject.NULL).put("last_use", a.lastUse ?: JSONObject.NULL)
            .put("longest", longest ?: JSONObject.NULL).put("hourly", JSONArray(a.hourly.map { it / 1000 }))
            .put("apps", apps).put("updated", now)
    }

    /**
     * A day's summary: re-read from Android while it can still change (today) or hasn't been saved yet; otherwise
     * from storage. A re-read never replaces saved data with less (Android may have dropped old events).
     */
    fun get(context: Context, day: LocalDate, store: Store = Store(context)): JSONObject {
        val stored = store.readDay(day)
        val (_, dayEnd) = bounds(day)
        if (stored != null && stored.optLong("updated") >= dayEnd) return stored
        val today = LocalDate.now()
        if (day.isAfter(today) || day.isBefore(today.minusDays(EVENT_DAYS)) || !UsageCollector.hasUsageAccess(context)) {
            return stored ?: empty(day)
        }
        val fresh = compute(context, day, store.settings())
        if (stored != null && fresh.optLong("total_s") < stored.optLong("total_s")) return stored
        if (fresh.optLong("total_s") > 0 || stored != null || !day.isBefore(today)) store.saveDay(fresh)
        return fresh
    }

    /** Add categories (with your overrides), per-category totals and "distracting" time for the screens. */
    fun forUi(day: JSONObject, settings: JSONObject): JSONObject {
        val out = JSONObject(day.toString())
        val overrides = settings.optJSONObject("categoryOverrides")
        val distracting = settings.optJSONArray("distracting")?.let { arr -> (0 until arr.length()).map { arr.getString(it) }.toSet() }.orEmpty()
        val cats = JSONObject()
        var distractingS = 0L
        val apps = out.optJSONArray("apps") ?: JSONArray()
        for (i in 0 until apps.length()) {
            val a = apps.getJSONObject(i)
            val cat = Categorize.of(a.getString("pkg"), a.getString("name"), a.optString("hint").ifEmpty { null }, overrides)
            a.put("cat", cat)
            cats.put(cat, cats.optLong(cat) + a.optLong("s"))
            if (cat in distracting && a.getString("pkg") != Categorize.PRIVATE_KEY) distractingS += a.optLong("s")
        }
        return out.put("cats", cats).put("distracting_s", distractingS)
    }

    /** Re-apply the private-apps list to everything already saved (after you add a keyword). */
    fun rescrub(store: Store) {
        val keywords = store.settings().optJSONArray("privateKeywords")
        for (day in store.storedDays()) {
            val d = store.readDay(day) ?: continue
            val apps = d.optJSONArray("apps") ?: continue
            val kept = JSONArray()
            var priv: JSONObject? = null
            var changed = false
            for (i in 0 until apps.length()) {
                val a = apps.getJSONObject(i)
                if (a.getString("pkg") != Categorize.PRIVATE_KEY && Categorize.isPrivate(a.getString("pkg"), a.getString("name"), keywords)) {
                    changed = true
                    priv = (priv ?: JSONObject().put("pkg", Categorize.PRIVATE_KEY).put("name", Categorize.PRIVATE_NAME).put("s", 0).put("opens", 0))
                        .let { it.put("s", it.getLong("s") + a.optLong("s")).put("opens", it.getInt("opens") + a.optInt("opens")) }
                } else if (a.getString("pkg") == Categorize.PRIVATE_KEY) {
                    priv = priv?.let { it.put("s", it.getLong("s") + a.optLong("s")).put("opens", it.getInt("opens") + a.optInt("opens")) } ?: a
                } else kept.put(a)
            }
            val lg = d.optJSONObject("longest")
            if (lg != null && Categorize.isPrivate(lg.optString("pkg"), lg.optString("name"), keywords)) {
                lg.put("pkg", Categorize.PRIVATE_KEY).put("name", "a private app"); changed = true
            }
            if (!changed) continue
            priv?.let { kept.put(it) }
            store.saveDay(d.put("apps", kept))
        }
    }

    /** One day in the format WorkPulse on a laptop expects (optional laptop sync). */
    fun laptopPayload(context: Context, day: LocalDate, deviceName: String): JSONObject {
        val store = Store(context)
        val d = get(context, day, store)
        val apps = JSONArray()
        val list = d.optJSONArray("apps") ?: JSONArray()
        for (i in 0 until list.length()) {
            val a = list.getJSONObject(i)
            if (a.optLong("s") < 30) continue
            val private = a.getString("pkg") == Categorize.PRIVATE_KEY
            apps.put(JSONObject().put("name", if (private) "(private)" else a.getString("name")).put("seconds", a.optLong("s"))
                .apply { if (!private) put("package", a.getString("pkg")); a.optString("hint").takeIf { it.isNotEmpty() }?.let { put("category_hint", it) } })
        }
        return JSONObject().put("day", day.toString()).put("device", deviceName).put("total_s", d.optLong("total_s"))
            .put("apps", apps).put("pickups", d.optInt("pickups"))
    }
}
