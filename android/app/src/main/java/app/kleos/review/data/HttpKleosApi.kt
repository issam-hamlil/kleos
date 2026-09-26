package app.kleos.review.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody

/**
 * OkHttp client for the Kleos API.
 *
 * The token is only ever placed in the Authorization header - never in a URL,
 * where it would end up in server and proxy logs.
 */
class HttpKleosApi(
    config: ServerConfig,
    private val client: OkHttpClient,
    private val json: Json = KleosJson,
) : KleosApi {

    private val base: HttpUrl = config.baseUrl.toHttpUrl()

    override val authHeaders: Map<String, String> = mapOf("Authorization" to "Bearer ${config.token}")

    override suspend fun pending(): List<ClipDto> =
        get(url("api", "pending"), ListSerializer(ClipDto.serializer()))

    override suspend fun clip(videoId: String): ClipDto =
        get(url("api", "clips", videoId), ClipDto.serializer())

    override suspend fun platforms(): List<PlatformDto> =
        get(url("api", "platforms"), ListSerializer(PlatformDto.serializer()))

    override suspend fun approve(videoId: String, platforms: List<String>): ApproveResponse {
        val body = json.encodeToString(ApproveRequest.serializer(), ApproveRequest(platforms))
        return post(url("api", "clips", videoId, "approve"), body.toRequestBody(JSON), ApproveResponse.serializer())
    }

    override suspend fun reject(videoId: String): RejectResponse =
        post(url("api", "clips", videoId, "reject"), EMPTY_BODY, RejectResponse.serializer())

    override suspend fun analytics(): AnalyticsDto =
        get(url("api", "analytics"), AnalyticsDto.serializer())

    override suspend fun history(limit: Int): List<HistoryEntryDto> {
        val target = url("api", "history").newBuilder().addQueryParameter("limit", limit.toString()).build()
        return get(target, ListSerializer(HistoryEntryDto.serializer()))
    }

    override fun streamUrl(videoId: String): String = url("api", "clips", videoId, "stream").toString()

    /** Appends path segments one at a time, so a video id is always encoded as a single segment. */
    private fun url(vararg segments: String): HttpUrl {
        val builder = base.newBuilder()
        segments.forEach { builder.addPathSegment(it) }
        return builder.build()
    }

    private suspend fun <T> get(url: HttpUrl, serializer: KSerializer<T>): T =
        execute(authorized(url).get().build(), serializer)

    private suspend fun <T> post(url: HttpUrl, body: RequestBody, serializer: KSerializer<T>): T =
        execute(authorized(url).post(body).build(), serializer)

    private fun authorized(url: HttpUrl): Request.Builder {
        val builder = Request.Builder().url(url).header("Accept", "application/json")
        authHeaders.forEach { (name, value) -> builder.header(name, value) }
        return builder
    }

    private suspend fun <T> execute(request: Request, serializer: KSerializer<T>): T =
        withContext(Dispatchers.IO) {
            client.newCall(request).execute().use { response ->
                val text = response.body?.string().orEmpty()
                val envelope = runCatching {
                    json.decodeFromString(Envelope.serializer(serializer), text)
                }.getOrNull()
                if (!response.isSuccessful || envelope == null || !envelope.success) {
                    throw ApiException(response.code, envelope?.error ?: "HTTP ${response.code}")
                }
                envelope.data ?: throw ApiException(response.code, "empty response")
            }
        }

    private companion object {
        val JSON = "application/json".toMediaType()
        val EMPTY_BODY: RequestBody = ByteArray(0).toRequestBody(JSON)
    }
}
