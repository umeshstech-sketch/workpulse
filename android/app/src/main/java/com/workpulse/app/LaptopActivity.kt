package com.workpulse.app

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.view.WindowInsets
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.text.DateFormat
import java.util.Date
import kotlin.concurrent.thread

/**
 * Optional: also send this phone's usage to WorkPulse on a laptop (home Wi-Fi, or Tailscale when you're out).
 * The app works fully without it.
 */
class LaptopActivity : Activity() {
    private lateinit var prefs: Prefs

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        window.statusBarColor = BG
        window.navigationBarColor = BG
        if (!handlePairLink(intent)) render()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handlePairLink(intent)
    }

    /** workpulse://pair?host=192.168.x.x:8787&code=123456&alt=100.x.y.z:8787 (QR on the laptop) */
    private fun handlePairLink(intent: Intent?): Boolean {
        val data = intent?.data ?: return false
        if (data.scheme != "workpulse" || data.host != "pair") return false
        val alt = data.getQueryParameter("alt").orEmpty().split(',').map { it.trim() }.filter { it.isNotEmpty() }
        showSetup(data.getQueryParameter("host"), data.getQueryParameter("code"), autoConnect = true, alt = alt)
        return true
    }

    private fun render() = if (prefs.isPaired) showConnected() else showSetup()

    private fun showConnected() {
        val col = column()
        col.addView(text("Laptop sync is on", 22f, bold = true, center = true), spaced())
        val last = prefs.lastSync.takeIf { it > 0 }?.let { DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(it)) } ?: "not yet"
        col.addView(text("Your phone usage is also sent to WorkPulse on ${prefs.activeHost ?: prefs.host} every 15 minutes.\n\n" +
            "Last sync: $last" + (prefs.lastError?.let { "\n($it)" } ?: ""), 15f, muted = true, center = true), spaced())
        col.addView(button("Sync now") { SyncWorker.syncNow(this); finish() }, spaced(dp(52)))
        col.addView(button("Disconnect from the laptop", primary = false) {
            prefs.clearPairing()
            SyncWorker.cancel(this)
            showSetup(message = "Disconnected. The app keeps working on its own.")
        }, spaced(dp(52)))
        col.addView(button("Back", primary = false) { finish() }, spaced(dp(52)))
        setScreen(col)
    }

    private fun showSetup(host: String? = null, code: String? = null, autoConnect: Boolean = false, message: String? = null,
                          alt: List<String> = emptyList()) {
        val col = column()
        col.addView(text("Connect to a laptop (optional)", 22f, bold = true, center = true), spaced())
        col.addView(text("Only if you also run WorkPulse on your computer. On the laptop: dashboard → Settings → Connect a phone " +
            "(or .\\workpulse connect). WorkPulse on this phone works fine without it.", 15f, muted = true, center = true), spaced())
        val hostIn = input("Laptop address, e.g. 192.168.1.20:8787", InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI)
        hostIn.setText(host ?: prefs.host ?: "")
        val codeIn = input("6-digit code", InputType.TYPE_CLASS_NUMBER)
        codeIn.setText(code ?: "")
        val status = text(message ?: "", 14f, muted = true, center = true)
        val btn = button("Connect") {}
        col.addView(hostIn, spaced()); col.addView(codeIn, spaced()); col.addView(btn, spaced(dp(52))); col.addView(status, spaced())
        col.addView(button("Back", primary = false) { finish() }, spaced(dp(52)))
        btn.setOnClickListener {
            val h = normalizeHost(hostIn.text.toString())
            val c = codeIn.text.toString().filter { it.isDigit() }
            if (h.isEmpty() || c.length != 6) { status.text = "Enter the laptop address and the 6-digit code."; return@setOnClickListener }
            btn.isEnabled = false
            status.text = "Connecting…"
            val name = Build.MODEL ?: "Android phone"
            thread {
                try {
                    // From a QR code: pair over whichever of the laptop's addresses answers from where you are.
                    val use = if (alt.isEmpty()) h else (listOf(h) + alt).firstOrNull { Api.reachable(it) } ?: h
                    val res = Api.pair(use, c, name)
                    prefs.host = h
                    prefs.altHosts = alt
                    prefs.activeHost = use
                    prefs.token = res.getString("token")
                    prefs.deviceName = res.optString("name", name)
                    runOnUiThread { SyncWorker.schedule(this); SyncWorker.syncNow(this); showConnected() }
                } catch (e: Api.HttpError) {
                    runOnUiThread { status.text = e.message; btn.isEnabled = true }
                } catch (e: Exception) {
                    runOnUiThread {
                        status.text = "Can't reach $h. Same Wi-Fi (or Tailscale on)? Is phone access on on the laptop (.\\workpulse lan on / remote on)?"
                        btn.isEnabled = true
                    }
                }
            }
        }
        setScreen(col)
        if (autoConnect && !host.isNullOrBlank() && !code.isNullOrBlank()) btn.performClick()
    }

    private fun normalizeHost(raw: String): String {
        var h = raw.trim().removePrefix("http://").removePrefix("https://").substringBefore('/')
        if (h.isNotEmpty() && !h.contains(':')) h += ":8787"
        return h
    }

    // ---- tiny UI helpers ----

    private fun setScreen(v: View) = setContentView(ScrollView(this).apply { setBackgroundColor(BG); addView(v) }.padForSystemBars())
    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

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
    private fun column() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(24), dp(48), dp(24), dp(24))
        gravity = Gravity.CENTER_HORIZONTAL
    }
    private fun spaced(height: Int = WRAP_CONTENT) = LinearLayout.LayoutParams(MATCH_PARENT, height).apply { topMargin = dp(14) }
    private fun text(s: String, size: Float, bold: Boolean = false, muted: Boolean = false, center: Boolean = false) = TextView(this).apply {
        text = s
        textSize = size
        setTextColor(if (muted) MUTED else INK)
        if (bold) typeface = Typeface.DEFAULT_BOLD
        if (center) gravity = Gravity.CENTER
    }
    private fun input(hint: String, type: Int) = EditText(this).apply {
        this.hint = hint
        inputType = type
        setTextColor(INK)
        setHintTextColor(MUTED)
        textSize = 18f
        setSingleLine()
    }
    private fun button(label: String, primary: Boolean = true, onClick: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        textSize = 16f
        setTextColor(if (primary) Color.WHITE else INK)
        setBackgroundColor(if (primary) ACCENT else SURFACE)
        setOnClickListener { onClick() }
    }

    companion object {
        private val BG = Color.parseColor("#0D0D0D")
        private val SURFACE = Color.parseColor("#232321")
        private val INK = Color.parseColor("#F0EFEC")
        private val MUTED = Color.parseColor("#898781")
        private val ACCENT = Color.parseColor("#3987E5")
    }
}
