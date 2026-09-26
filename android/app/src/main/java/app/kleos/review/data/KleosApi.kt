package app.kleos.review.data

import java.io.IOException

/** The Kleos server's review API. One implementation talks HTTP; tests use fakes. */
interface KleosApi {
    suspend fun pending(): List<ClipDto>

    suspend fun clip(videoId: String): ClipDto

    suspend fun platforms(): List<PlatformDto>

    suspend fun approve(videoId: String, platforms: List<String>): ApproveResponse

    suspend fun reject(videoId: String): RejectResponse

    suspend fun analytics(): AnalyticsDto

    suspend fun history(limit: Int = 50): List<HistoryEntryDto>

    /** URL of the clip's video, for the player. Requires [authHeaders]. */
    fun streamUrl(videoId: String): String

    /** Headers every request, including video streaming, must carry. */
    val authHeaders: Map<String, String>
}

/** Supplies the API for the current server settings, or null when not configured. */
fun interface ApiProvider {
    fun api(): KleosApi?
}

/** A request the server answered with an error, carrying its HTTP status. */
class ApiException(val status: Int, message: String) : IOException(message) {
    val isUnauthorized: Boolean get() = status == 401
}
