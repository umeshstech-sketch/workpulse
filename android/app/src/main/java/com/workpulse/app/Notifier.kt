package com.workpulse.app

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build

/** The app's notifications: app limits, daily goal, bedtime, focus timer. */
object Notifier {
    const val LIMITS = "limits"
    const val BEDTIME = "bedtime"
    const val FOCUS = "focus"

    fun allowed(context: Context): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun channels(nm: NotificationManager) {
        nm.createNotificationChannel(NotificationChannel(LIMITS, "App limits & daily goal", NotificationManager.IMPORTANCE_DEFAULT))
        nm.createNotificationChannel(NotificationChannel(BEDTIME, "Bedtime reminder", NotificationManager.IMPORTANCE_DEFAULT))
        nm.createNotificationChannel(NotificationChannel(FOCUS, "Focus timer", NotificationManager.IMPORTANCE_HIGH))
    }

    fun show(context: Context, id: Int, channel: String, title: String, text: String, view: String = "today") {
        if (!allowed(context)) return
        val nm = context.getSystemService(NotificationManager::class.java)
        channels(nm)
        val open = PendingIntent.getActivity(context, id, Intent(context, MainActivity::class.java).putExtra("view", view)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = Notification.Builder(context, channel)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        nm.notify(id, n)
    }
}
