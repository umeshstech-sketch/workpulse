package com.workpulse.app

import org.json.JSONArray
import org.json.JSONObject

/** Sorts phone apps into categories, and decides which apps are private (never named). */
object Categorize {
    val CATEGORIES = listOf("Social", "Entertainment", "Games", "Communication", "Productivity", "Learning", "Browsing", "Other")
    const val PRIVATE_KEY = "private"
    const val PRIVATE_NAME = "Private apps"

    // Lowercase text found in the app name or package -> category. First match wins.
    private val KEYWORDS: List<Pair<String, String>> = listOf(
        "youtube studio" to "Productivity", "capcut" to "Productivity",
        "instagram" to "Social", "facebook" to "Social", "snapchat" to "Social", "twitter" to "Social", "threads" to "Social",
        "reddit" to "Social", "pinterest" to "Social", "linkedin" to "Social", "sharechat" to "Social", "moj" to "Social",
        "josh" to "Social", "tiktok" to "Social", "tumblr" to "Social", "quora" to "Social",
        "youtube" to "Entertainment", "netflix" to "Entertainment", "hotstar" to "Entertainment", "primevideo" to "Entertainment",
        "prime video" to "Entertainment", "jiocinema" to "Entertainment", "zee5" to "Entertainment", "sonyliv" to "Entertainment",
        "mxplayer" to "Entertainment", "spotify" to "Entertainment", "gaana" to "Entertainment", "wynk" to "Entertainment",
        "jiosaavn" to "Entertainment", "music" to "Entertainment", "video" to "Entertainment", "gallery" to "Entertainment",
        "bgmi" to "Games", "pubg" to "Games", "freefire" to "Games", "free fire" to "Games", "ludo" to "Games",
        "candy" to "Games", "clash" to "Games", "minecraft" to "Games", "roblox" to "Games", "chess" to "Games", "game" to "Games",
        "whatsapp" to "Communication", "telegram" to "Communication", "signal" to "Communication", "discord" to "Communication",
        "slack" to "Communication", "gmail" to "Communication", "outlook" to "Communication", "teams" to "Communication",
        "meet" to "Communication", "zoom" to "Communication", "messag" to "Communication", "dialer" to "Communication",
        "contacts" to "Communication", "truecaller" to "Communication", "com.android.phone" to "Communication", "mail" to "Communication",
        "chatgpt" to "Learning", "claude" to "Learning", "gemini" to "Learning", "perplexity" to "Learning", "duolingo" to "Learning",
        "coursera" to "Learning", "udemy" to "Learning", "khan" to "Learning", "byju" to "Learning", "unacademy" to "Learning",
        "physicswallah" to "Learning", "kindle" to "Learning", "books" to "Learning", "dictionary" to "Learning", "wikipedia" to "Learning",
        "docs" to "Productivity", "sheets" to "Productivity", "slides" to "Productivity", "drive" to "Productivity",
        "calendar" to "Productivity", "keep" to "Productivity", "notion" to "Productivity", "office" to "Productivity",
        "word" to "Productivity", "excel" to "Productivity", "powerpoint" to "Productivity", "todo" to "Productivity",
        "tasks" to "Productivity", "notes" to "Productivity", "evernote" to "Productivity", "trello" to "Productivity",
        "github" to "Productivity", "termux" to "Productivity", "camscanner" to "Productivity", "adobe" to "Productivity",
        "chrome" to "Browsing", "browser" to "Browsing", "firefox" to "Browsing", "brave" to "Browsing", "opera" to "Browsing",
        "edge" to "Browsing", "sbrowser" to "Browsing", "news" to "Browsing", "inshorts" to "Browsing", "dailyhunt" to "Browsing",
    )

    val DEFAULT_PRIVATE = listOf(
        "bank", "paytm", "phonepe", "gpay", "google pay", "bhim", "ippb", "yono", "sbi", "hdfc", "icici", "axis", "kotak",
        "imobile", "wallet", "paisa", "payments", "keepass", "bitwarden", "1password", "authenticator", "incognito",
    )

    /** Android's own category for the app (set by the developer), used when no keyword matches. */
    private fun fromHint(hint: String?): String? = when (hint) {
        "game" -> "Games"
        "social" -> "Social"
        "video", "audio", "image" -> "Entertainment"
        "news" -> "Browsing"
        "productivity" -> "Productivity"
        else -> null
    }

    fun of(pkg: String, name: String, hint: String?, overrides: JSONObject?): String {
        overrides?.optString(pkg)?.takeIf { it in CATEGORIES }?.let { return it }
        if (pkg == PRIVATE_KEY) return "Other"
        val text = "${name.lowercase()} ${pkg.lowercase()}"
        KEYWORDS.firstOrNull { (k, _) -> k in text }?.let { return it.second }
        return fromHint(hint) ?: "Other"
    }

    fun isPrivate(pkg: String, name: String, keywords: JSONArray?): Boolean {
        val text = "${name.lowercase()} ${pkg.lowercase()}"
        val list = keywords ?: return false
        return (0 until list.length()).any { i -> list.optString(i).trim().lowercase().let { it.isNotEmpty() && it in text } }
    }
}
