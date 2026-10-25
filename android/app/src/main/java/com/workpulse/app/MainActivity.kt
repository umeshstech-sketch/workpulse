package com.workpulse.app

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.WindowInsets
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.widget.FrameLayout
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate

/**
 * WorkPulse for Android: a phone activity tracker that works entirely on this phone. The screens are a small
 * web page bundled in the app (assets/app); `window.WorkPulse` below gives them the data. Nothing is sent
 * anywhere unless you turn on the optional laptop sync.
 */
class MainActivity : Activity() {
    private var web: WebView? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = BG
        window.navigationBarColor = BG
        TrackerWorker.schedule(this)
        if (Prefs(this).isPaired) SyncWorker.schedule(this)
        val w = WebView(this).apply {
            setBackgroundColor(BG)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = false  // bundled assets only (file:///android_asset is always allowed)
            addJavascriptInterface(Bridge(), "WorkPulse")
            webChromeClient = object : WebChromeClient() {
                override fun onConsoleMessage(m: ConsoleMessage): Boolean {
                    android.util.Log.d("WorkPulse", "${m.message()} (${m.sourceId()}:${m.lineNumber()})")
                    return true
                }
            }
        }
        web = w
        // Android 15 draws apps edge-to-edge: keep the screens clear of the status bar, nav bar and keyboard.
        setContentView(FrameLayout(this).apply { setBackgroundColor(BG); addView(w, MATCH_PARENT, MATCH_PARENT) }.padForSystemBars())
        val view = intent?.getStringExtra("view")?.takeIf { it.matches(Regex("[a-z]+")) } ?: "today"
        w.loadUrl("file:///android_asset/app/index.html#view=$view")
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.getStringExtra("view")?.takeIf { it.matches(Regex("[a-z]+")) }?.let { js("window.wpShow && wpShow('$it')") }
    }

    override fun onResume() {
        super.onResume()
        js("window.wpResume && wpResume()")  // back from Settings (usage access) or another app: refresh
        if (Prefs(this).isPaired && UsageCollector.hasUsageAccess(this)) SyncWorker.syncNow(this)
    }

    override fun onDestroy() {
        web?.destroy(); web = null
        super.onDestroy()
    }

    @Deprecated("Activity back handling")
    override fun onBackPressed() {
        val w = web
        if (w == null) {
            @Suppress("DEPRECATION") super.onBackPressed()
            return
        }
        w.evaluateJavascript("window.wpBack ? wpBack() : false") { handled ->
            if (handled != "true") @Suppress("DEPRECATION") super.onBackPressed()
        }
    }

    private fun js(code: String) = runOnUiThread { web?.evaluateJavascript(code, null) }

    @Deprecated("Activity results")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == EXPORT && resultCode == RESULT_OK && data?.data != null) {
            val ok = runCatching {
                contentResolver.openOutputStream(data.data!!)!!.use { it.write(exportCsv().toByteArray()) }
            }.isSuccess
            js("window.wpToast && wpToast(${JSONObject.quote(if (ok) "Exported ✓" else "Export failed")})")
        } else @Suppress("DEPRECATION") super.onActivityResult(requestCode, resultCode, data)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        js("window.wpResume && wpResume()")
    }

    private fun exportCsv(): String {
        val store = Store(this)
        val settings = store.settings()
        val sb = StringBuilder("date,app,package,category,minutes,opens\n")
        fun q(s: String) = "\"" + s.replace("\"", "\"\"") + "\""
        for (day in store.storedDays()) {
            val d = Tracker.forUi(store.readDay(day) ?: continue, settings)
            val apps = d.optJSONArray("apps") ?: continue
            for (i in 0 until apps.length()) {
                val a = apps.getJSONObject(i)
                val minutes = String.format(java.util.Locale.US, "%.1f", a.optLong("s") / 60.0)
                sb.append("$day,${q(a.getString("name"))},${q(a.getString("pkg"))},${a.optString("cat")},$minutes,${a.optInt("opens")}\n")
            }
        }
        return sb.toString()
    }

    /** Called from the screens (window.WorkPulse). Every method returns JSON text. */
    inner class Bridge {
        private val ctx get() = this@MainActivity
        private val store get() = Store(ctx)

        private fun date(s: String): LocalDate = runCatching { LocalDate.parse(s) }.getOrDefault(LocalDate.now())

        @JavascriptInterface fun status(): String = JSONObject()
            .put("usageAccess", UsageCollector.hasUsageAccess(ctx))
            .put("notifications", Notifier.allowed(ctx))
            .put("version", BuildConfig.VERSION_NAME)
            .put("firstDay", store.storedDays().firstOrNull()?.toString() ?: JSONObject.NULL)
            .toString()

        @JavascriptInterface fun day(iso: String): String {
            val s = store
            return Tracker.forUi(Tracker.get(ctx, date(iso), s), s.settings()).toString()
        }

        /** The last `n` days up to and including `endIso`, oldest first. */
        @JavascriptInterface fun range(n: Int, endIso: String): String {
            val s = store
            val settings = s.settings()
            val end = date(endIso)
            val out = JSONArray()
            for (i in (n.coerceIn(1, 120) - 1) downTo 0) out.put(Tracker.forUi(Tracker.get(ctx, end.minusDays(i.toLong()), s), settings))
            return out.toString()
        }

        @JavascriptInterface fun settings(): String = store.settings().toString()

        @JavascriptInterface fun saveSettings(changes: String): String {
            val s = store
            val before = s.settings().optJSONArray("privateKeywords").toString()
            val after = s.saveSettings(JSONObject(changes))
            if (after.optJSONArray("privateKeywords").toString() != before) Tracker.rescrub(s)
            return after.toString()
        }

        @JavascriptInterface fun getData(key: String): String = store.getData("ui:$key") ?: "null"
        @JavascriptInterface fun setData(key: String, json: String) = store.setData("ui:$key", json)

        @JavascriptInterface fun focus(): String = Focus.state(ctx).toString()
        @JavascriptInterface fun focusStart(minutes: Int, label: String): String = Focus.start(ctx, minutes.coerceIn(1, 240), label).toString()
        @JavascriptInterface fun focusStop(): String = (Focus.finish(ctx, store, completed = false) ?: JSONObject()).toString()

        @JavascriptInterface fun openUsageAccess() = runOnUiThread { startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)) }

        @JavascriptInterface fun requestNotifications() = runOnUiThread {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 7)
        }

        @JavascriptInterface fun exportCsv() = runOnUiThread {
            @Suppress("DEPRECATION")
            startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("text/csv")
                .putExtra(Intent.EXTRA_TITLE, "workpulse-phone-${LocalDate.now()}.csv"), EXPORT)
        }

        @JavascriptInterface fun wipe(): String {
            val s = store
            Focus.finish(ctx, s, completed = false)
            s.wipe()
            return "true"
        }

        @JavascriptInterface fun laptop(): String {
            val p = Prefs(ctx)
            return JSONObject().put("paired", p.isPaired).put("host", p.activeHost ?: p.host ?: JSONObject.NULL)
                .put("lastSync", p.lastSync).put("lastError", p.lastError ?: JSONObject.NULL).toString()
        }

        @JavascriptInterface fun openLaptop() = runOnUiThread { startActivity(Intent(ctx, LaptopActivity::class.java)) }

        // ---- AI coach ----
        @JavascriptInterface fun coachStatus(): String = JSONObject().put("hasKey", !store.coachKey.isNullOrBlank()).toString()

        @JavascriptInterface fun setCoachKey(key: String): String {
            val k = key.trim()
            // Gemini keys start with "AQ." (new) or "AIza" (older); don't insist on either, just reject obvious junk.
            if (k.length < 20 || k.any { it.isWhitespace() }) return JSONObject().put("ok", false).put("error", "That doesn't look like a Gemini API key. Copy it again from aistudio.google.com.").toString()
            store.coachKey = k
            return JSONObject().put("ok", true).toString()
        }

        @JavascriptInterface fun clearCoachKey() { store.coachKey = null }

        /** Ask in the background; the answer arrives as wpCoachReply(id, {ok, text}). */
        @JavascriptInterface fun coachAsk(id: String, question: String, facts: String, historyJson: String) {
            val key = store.coachKey
            val history = runCatching {
                val a = JSONArray(historyJson)
                (0 until a.length()).map { a.getJSONObject(it).let { m -> m.optString("role") to m.optString("text") } }
            }.getOrDefault(emptyList())
            Thread {
                val res = if (key.isNullOrBlank()) Coach.Result.Failed("Add your Gemini API key in More → AI coach first.")
                    else Coach.ask(key, facts.take(6000), history, question.take(2000))
                val out = when (res) {
                    is Coach.Result.Reply -> JSONObject().put("ok", true).put("text", res.text)
                    is Coach.Result.Failed -> JSONObject().put("ok", false).put("text", res.message)
                }
                js("window.wpCoachReply && wpCoachReply(${JSONObject.quote(id)}, $out)")
            }.start()
        }
    }

    private fun <T : View> T.padForSystemBars(): T {
        setOnApplyWindowInsetsListener { v, insets ->
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                val i = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.ime())
                v.setPadding(i.left, i.top, i.right, i.bottom)
            } else {
                @Suppress("DEPRECATION")
                v.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop, insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            }
            insets
        }
        requestApplyInsets()
        return this
    }

    companion object {
        private const val EXPORT = 51
        private val BG = Color.parseColor("#0D0D0D")
    }
}
