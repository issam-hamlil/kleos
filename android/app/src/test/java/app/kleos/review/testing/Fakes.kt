package app.kleos.review.testing

import app.kleos.review.data.AnalyticsDto
import app.kleos.review.data.ApproveResponse
import app.kleos.review.data.ClipDto
import app.kleos.review.data.ConfigStore
import app.kleos.review.data.HistoryEntryDto
import app.kleos.review.data.KleosApi
import app.kleos.review.data.PlatformDto
import app.kleos.review.data.PublishResultDto
import app.kleos.review.data.RejectResponse
import app.kleos.review.data.ServerConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestDispatcher
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.rules.TestWatcher
import org.junit.runner.Description

/** Routes viewModelScope onto a test dispatcher. */
@OptIn(ExperimentalCoroutinesApi::class)
class MainDispatcherRule(val dispatcher: TestDispatcher = UnconfinedTestDispatcher()) : TestWatcher() {
    override fun starting(description: Description) = Dispatchers.setMain(dispatcher)

    override fun finished(description: Description) = Dispatchers.resetMain()
}

fun sampleClip(videoId: String = "vid1", status: String = "pending") = ClipDto(
    videoId = videoId,
    title = "Team A 2-1 Team B",
    channelId = "UC_one",
    watchUrl = "https://www.youtube.com/watch?v=$videoId",
    publishedAt = "2026-09-26T10:00:00+00:00",
    createdAt = "2026-09-26T10:01:00+00:00",
    expiresAt = "2026-09-26T22:01:00+00:00",
    durationS = 92.0,
    status = status,
)

/** Scriptable API: set the return values or errors each call should produce. */
class FakeKleosApi : KleosApi {
    var pendingResult: () -> List<ClipDto> = { listOf(sampleClip()) }
    var clipResult: (String) -> ClipDto = { sampleClip(it) }
    var platformsResult: () -> List<PlatformDto> = {
        listOf(PlatformDto("facebook", 7200), PlatformDto("instagram", 900), PlatformDto("x", 140))
    }
    var approveResult: (String, List<String>) -> ApproveResponse = { id, names ->
        ApproveResponse(id, names.map { PublishResultDto(it, ok = true, remoteId = "${it}_1") })
    }
    var rejectError: Exception? = null
    var analyticsResult: () -> AnalyticsDto = { AnalyticsDto(clips = mapOf("pending" to 1)) }
    var historyResult: () -> List<HistoryEntryDto> = { emptyList() }

    val approveCalls = mutableListOf<Pair<String, List<String>>>()
    val rejectCalls = mutableListOf<String>()

    override suspend fun pending() = pendingResult()
    override suspend fun clip(videoId: String) = clipResult(videoId)
    override suspend fun platforms() = platformsResult()

    override suspend fun approve(videoId: String, platforms: List<String>): ApproveResponse {
        approveCalls += videoId to platforms
        return approveResult(videoId, platforms)
    }

    override suspend fun reject(videoId: String): RejectResponse {
        rejectCalls += videoId
        rejectError?.let { throw it }
        return RejectResponse(videoId, "rejected")
    }

    override suspend fun analytics() = analyticsResult()
    override suspend fun history(limit: Int) = historyResult()
    override fun streamUrl(videoId: String) = "https://kleos.test/api/clips/$videoId/stream"
    override val authHeaders = mapOf("Authorization" to "Bearer test")
}

class InMemoryConfigStore(var saved: ServerConfig? = null) : ConfigStore {
    override fun load() = saved

    override fun save(config: ServerConfig) {
        saved = config
    }
}
