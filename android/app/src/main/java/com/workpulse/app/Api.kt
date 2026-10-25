package com.workpulse.app

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Tiny HTTP client for the laptop (plain HttpURLConnection; no extra libraries). */
object Api {
    class HttpError(val code: Int, message: String) : IOException(message)

    fun request(base: String, path: String, method: String = "GET", body: String? = null, token: String? = null): JSONObject {
        val conn = (URL(base.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 5_000
            readTimeout = 20_000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("X-WorkPulse-UI", "1")
            if (token != null) setRequestProperty("Authorization", "Bearer $token")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
            }
        }
        try {
            if (body != null) conn.outputStream.use { it.write(body.toByteArray()) }
            val code = conn.responseCode
            val text = (if (code in 200..299) conn.inputStream else conn.errorStream)?.bufferedReader()?.use { it.readText() } ?: ""
            if (code !in 200..299) {
                val detail = runCatching { JSONObject(text).optString("detail") }.getOrNull()
                throw HttpError(code, detail?.takeIf { it.isNotBlank() } ?: "HTTP $code")
            }
            return if (text.isBlank()) JSONObject() else JSONObject(text)
        } finally {
            conn.disconnect()
        }
    }

    /** Trade the 6-digit code shown on the laptop for this phone's token. */
    fun pair(host: String, code: String, name: String): JSONObject =
        request("http://$host", "/api/pair", "POST",
            JSONObject().put("code", code.filter { it.isDigit() }).put("name", name).put("kind", "android").toString())

    /** Is WorkPulse answering at this address? (Quick check, so trying several addresses stays fast.) */
    fun reachable(host: String): Boolean = try {
        val conn = (URL("http://$host/api/ping").openConnection() as HttpURLConnection).apply {
            connectTimeout = 2_500
            readTimeout = 4_000
        }
        try {
            conn.responseCode == 200 && conn.inputStream.bufferedReader().use { it.readText() }.contains("workpulse")
        } finally {
            conn.disconnect()
        }
    } catch (e: IOException) {
        false
    }

    /**
     * The first laptop address that answers: home Wi-Fi, or Tailscale when you're out. Remembers the winner so
     * it's tried first next time. Null = laptop not reachable from here right now. Call off the main thread.
     */
    fun findHost(prefs: Prefs): String? = prefs.allHosts.firstOrNull { reachable(it) }?.also { prefs.activeHost = it }

    /** Pick up addresses the laptop added later (e.g. away-from-home access turned on), without re-pairing. */
    fun refreshHosts(prefs: Prefs, host: String, token: String) {
        val hosts = runCatching { request("http://$host", "/api/whoami", token = token).optJSONArray("hosts") }.getOrNull() ?: return
        val list = (0 until hosts.length()).map { hosts.getString(it) }.filter { it.isNotBlank() }
        if (list.isNotEmpty()) prefs.altHosts = list
    }
}
