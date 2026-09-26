package app.kleos.review.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** Every Kleos API response: `{"success": bool, "data": ..., "error": str|null}`. */
@Serializable
data class Envelope<T>(
    val success: Boolean,
    val data: T? = null,
    val error: String? = null,
)

@Serializable
data class ClipDto(
    @SerialName("video_id") val videoId: String,
    val title: String,
    @SerialName("channel_id") val channelId: String,
    @SerialName("watch_url") val watchUrl: String,
    @SerialName("published_at") val publishedAt: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("expires_at") val expiresAt: String,
    @SerialName("duration_s") val durationS: Double,
    val status: String,
    val platforms: List<String> = emptyList(),
)

@Serializable
data class PlatformDto(
    val name: String,
    @SerialName("max_duration_s") val maxDurationS: Int,
)

@Serializable
data class ApproveRequest(val platforms: List<String>)

@Serializable
data class PublishResultDto(
    val platform: String,
    val ok: Boolean,
    @SerialName("remote_id") val remoteId: String = "",
    val error: String = "",
)

@Serializable
data class ApproveResponse(
    @SerialName("video_id") val videoId: String,
    val results: List<PublishResultDto>,
)

@Serializable
data class RejectResponse(
    @SerialName("video_id") val videoId: String,
    val status: String,
)

@Serializable
data class PlatformStatsDto(val published: Int, val failed: Int)

@Serializable
data class AnalyticsDto(
    val clips: Map<String, Int>,
    @SerialName("approval_rate") val approvalRate: Double? = null,
    @SerialName("avg_review_minutes") val avgReviewMinutes: Double? = null,
    val platforms: Map<String, PlatformStatsDto> = emptyMap(),
    @SerialName("publishing_enabled") val publishingEnabled: Boolean = true,
)

@Serializable
data class HistoryEntryDto(
    @SerialName("video_id") val videoId: String,
    val title: String,
    val platform: String,
    val ok: Boolean,
    @SerialName("remote_id") val remoteId: String = "",
    val error: String = "",
    val at: String,
)

/** Tolerant of fields the server adds later, so an older app keeps working. */
val KleosJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
}
