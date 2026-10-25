package com.workpulse.app

import android.content.Context

/** Where the laptop is and this phone's device token (app-private storage). */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("workpulse", Context.MODE_PRIVATE)

    var host: String?  // "192.168.1.20:8787" (the address it was paired with)
        get() = sp.getString("host", null)
        set(v) = sp.edit().putString("host", v).apply()

    /** Every address the laptop says it can be reached at (home Wi-Fi, Tailscale IP, Tailscale name). */
    var altHosts: List<String>
        get() = sp.getString("alt_hosts", "").orEmpty().split(',').map { it.trim() }.filter { it.isNotEmpty() }
        set(v) = sp.edit().putString("alt_hosts", v.joinToString(",")).apply()

    /** The address that worked last time (tried first). */
    var activeHost: String?
        get() = sp.getString("active_host", null)
        set(v) = sp.edit().putString("active_host", v).apply()

    var token: String?
        get() = sp.getString("token", null)
        set(v) = sp.edit().putString("token", v).apply()

    var deviceName: String?
        get() = sp.getString("name", null)
        set(v) = sp.edit().putString("name", v).apply()

    var lastSync: Long
        get() = sp.getLong("last_sync", 0L)
        set(v) = sp.edit().putLong("last_sync", v).apply()

    var lastError: String?
        get() = sp.getString("last_error", null)
        set(v) = sp.edit().putString("last_error", v).apply()

    var askedUsageAccess: Boolean
        get() = sp.getBoolean("asked_usage", false)
        set(v) = sp.edit().putBoolean("asked_usage", v).apply()

    /** Addresses to try, best guess first. */
    val allHosts: List<String> get() = listOfNotNull(activeHost, host).plus(altHosts).filter { it.isNotBlank() }.distinct()
    val isPaired: Boolean get() = !host.isNullOrBlank() && !token.isNullOrBlank()

    fun clearPairing() {
        sp.edit().remove("token").remove("last_sync").remove("last_error").remove("alt_hosts").remove("active_host").apply()
    }
}
