package app.kleos.review.ui.common

import java.time.Duration
import java.time.Instant
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException
import kotlin.math.roundToInt

/** Formatting shared by the screens. Pure functions, so they are unit tested directly. */
object Formatting {

    /** 92.4 -> "1:32". */
    fun duration(seconds: Double): String {
        val total = seconds.coerceAtLeast(0.0).roundToInt()
        return "%d:%02d".format(total / 60, total % 60)
    }

    /** Time left before a pending clip is deleted unreviewed. */
    fun expiresIn(expiresAt: String, now: Instant = Instant.now()): String {
        val deadline = parse(expiresAt) ?: return "Expiry unknown"
        val left = Duration.between(now, deadline)
        if (left.isNegative || left.isZero) return "Expiring now"
        val hours = left.toHours()
        val minutes = left.toMinutes() % 60
        return if (hours > 0) "Expires in ${hours}h ${minutes}m" else "Expires in ${minutes.coerceAtLeast(1)}m"
    }

    /** "Just now", "12m ago", "3h ago", "2d ago". */
    fun ago(timestamp: String, now: Instant = Instant.now()): String {
        val then = parse(timestamp) ?: return ""
        val elapsed = Duration.between(then, now)
        return when {
            elapsed.toMinutes() < 1 -> "Just now"
            elapsed.toHours() < 1 -> "${elapsed.toMinutes()}m ago"
            elapsed.toDays() < 1 -> "${elapsed.toHours()}h ago"
            else -> "${elapsed.toDays()}d ago"
        }
    }

    /** 0.666 -> "67%", null -> "-". */
    fun percent(rate: Double?): String = rate?.let { "${(it * 100).roundToInt()}%" } ?: "-"

    /** Average review time: "45s", "12m", "2h 5m", or "-" when there is no data. */
    fun reviewTime(minutes: Double?): String {
        if (minutes == null) return "-"
        val totalSeconds = (minutes * 60).roundToInt()
        return when {
            totalSeconds < 60 -> "${totalSeconds}s"
            totalSeconds < 3600 -> "${totalSeconds / 60}m"
            else -> "${totalSeconds / 3600}h ${(totalSeconds % 3600) / 60}m"
        }
    }

    /** "facebook" -> "Facebook", "x" -> "X". */
    fun platformLabel(name: String): String = when (name.lowercase()) {
        "x" -> "X"
        "facebook" -> "Facebook"
        "instagram" -> "Instagram"
        else -> name.replaceFirstChar { it.uppercase() }
    }

    private fun parse(timestamp: String): Instant? = try {
        OffsetDateTime.parse(timestamp).toInstant()
    } catch (error: DateTimeParseException) {
        null
    }
}
