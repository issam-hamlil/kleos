package app.kleos.review.notify

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import app.kleos.review.KleosApplication
import app.kleos.review.MainActivity
import app.kleos.review.R
import app.kleos.review.data.ApiException
import app.kleos.review.data.ClipDto
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Which clips in the queue the operator has not been told about yet. */
object NewClipDetector {
    fun newClips(pending: List<ClipDto>, announced: Set<String>): List<ClipDto> =
        pending.filter { it.videoId !in announced }
}

/**
 * Polls the review queue in the background and notifies about new clips.
 *
 * WorkManager's floor is 15 minutes. That is slower than a push, but needs no
 * Firebase project, no Google services on the server, and no extra secrets.
 */
class PendingCheckWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val container = (applicationContext as KleosApplication).container
        val api = container.api() ?: return Result.success()
        val pending = try {
            api.pending()
        } catch (error: ApiException) {
            // Bad token or API switched off: retrying will not fix it. The app shows why.
            return Result.success()
        } catch (error: IOException) {
            return Result.retry()
        }
        val fresh = NewClipDetector.newClips(pending, container.settings.announcedClipIds())
        // Remember only what is still pending, so the set cannot grow without bound.
        container.settings.setAnnouncedClipIds(pending.map { it.videoId }.toSet())
        if (fresh.isNotEmpty()) ClipNotifier.notifyNewClips(applicationContext, fresh)
        return Result.success()
    }

    companion object {
        private const val WORK_NAME = "kleos-pending-check"

        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<PendingCheckWorker>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(WORK_NAME, ExistingPeriodicWorkPolicy.KEEP, request)
        }
    }
}

object ClipNotifier {
    private const val CHANNEL_ID = "new_clips"
    private const val NOTIFICATION_ID = 1001

    fun ensureChannel(context: Context) {
        val channel = NotificationChannel(CHANNEL_ID, "Clips to review", NotificationManager.IMPORTANCE_DEFAULT)
            .apply { description = "New highlights waiting for your approval" }
        context.getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    fun notifyNewClips(context: Context, clips: List<ClipDto>) {
        if (!canNotify(context)) return
        val open = PendingIntent.getActivity(
            context,
            0,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val title = if (clips.size == 1) "New clip to review" else "${clips.size} new clips to review"
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(clips.first().title)
            .setStyle(NotificationCompat.InboxStyle().also { style -> clips.take(5).forEach { style.addLine(it.title) } })
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        try {
            NotificationManagerCompat.from(context).notify(NOTIFICATION_ID, notification)
        } catch (error: SecurityException) {
            // Permission revoked between the check and the call; nothing else to do.
        }
    }

    private fun canNotify(context: Context): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
}
