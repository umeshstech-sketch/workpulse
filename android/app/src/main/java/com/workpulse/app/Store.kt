package com.workpulse.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.LocalDate

/**
 * Everything the app keeps, in its private storage on this phone (nothing leaves it unless you turn on laptop
 * sync). One small JSON file per day, plus settings, habits and focus sessions in SharedPreferences.
 */
class Store(context: Context) {
    private val dir = File(context.filesDir, "days").apply { mkdirs() }
    private val sp = context.getSharedPreferences("local", Context.MODE_PRIVATE)

    // ---- days ----
    fun readDay(day: LocalDate): JSONObject? = File(dir, "$day.json").takeIf { it.exists() }?.let {
        runCatching { JSONObject(it.readText()) }.getOrNull()
    }

    fun saveDay(json: JSONObject) {
        val f = File(dir, "${json.getString("day")}.json")
        val tmp = File(dir, "${f.name}.tmp")
        tmp.writeText(json.toString())
        tmp.renameTo(f)
    }

    fun storedDays(): List<LocalDate> =
        dir.listFiles { f -> f.name.endsWith(".json") }.orEmpty().mapNotNull { runCatching { LocalDate.parse(it.name.removeSuffix(".json")) }.getOrNull() }.sorted()

    // ---- settings ----
    fun settings(): JSONObject {
        val out = JSONObject(DEFAULTS)
        val saved = sp.getString("settings", null)?.let { runCatching { JSONObject(it) }.getOrNull() } ?: return out
        saved.keys().forEach { out.put(it, saved.get(it)) }
        return out
    }

    /** Merge `changes` (top-level keys) into the settings. */
    fun saveSettings(changes: JSONObject): JSONObject {
        val saved = sp.getString("settings", null)?.let { runCatching { JSONObject(it) }.getOrNull() } ?: JSONObject()
        changes.keys().forEach { saved.put(it, changes.get(it)) }
        sp.edit().putString("settings", saved.toString()).apply()
        return settings()
    }

    // ---- small JSON values (habits, focus) ----
    fun getData(key: String): String? = sp.getString("data:$key", null)
    fun setData(key: String, json: String?) {
        if (json == null) sp.edit().remove("data:$key").apply() else sp.edit().putString("data:$key", json).apply()
    }

    fun list(key: String): JSONArray = getData(key)?.let { runCatching { JSONArray(it) }.getOrNull() } ?: JSONArray()

    // ---- AI coach key (your own Gemini API key; app-private storage, never shown back) ----
    var coachKey: String?
        get() = sp.getString("coach_key", null)
        set(v) { if (v == null) sp.edit().remove("coach_key").apply() else sp.edit().putString("coach_key", v).apply() }

    // ---- once-only notification flags ----
    fun flagOnce(day: LocalDate, key: String): Boolean {
        val name = "flags:$day"
        val set = sp.getStringSet(name, emptySet()).orEmpty()
        if (key in set) return false
        val e = sp.edit().putStringSet(name, set + key)
        sp.all.keys.filter { it.startsWith("flags:") && it < "flags:${day.minusDays(2)}" }.forEach { e.remove(it) }
        e.apply()
        return true
    }

    fun wipe() {
        dir.listFiles().orEmpty().forEach { it.delete() }
        sp.edit().clear().apply()
    }

    companion object {
        val DEFAULTS: String = JSONObject()
            .put("dailyGoalMin", 180)
            .put("pickupGoal", 60)
            .put("bedtime", "23:00")
            .put("wake", "06:30")
            .put("bedtimeReminder", true)
            .put("notifyLimits", true)
            .put("limits", JSONObject())
            .put("categoryOverrides", JSONObject())
            .put("distracting", JSONArray(listOf("Social", "Entertainment", "Games")))
            .put("privateKeywords", JSONArray(Categorize.DEFAULT_PRIVATE))
            .put("theme", "auto")
            .toString()
    }
}
