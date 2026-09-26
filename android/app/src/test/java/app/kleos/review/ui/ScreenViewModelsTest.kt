package app.kleos.review.ui

import app.kleos.review.data.AnalyticsDto
import app.kleos.review.data.ApiException
import app.kleos.review.data.PlatformDto
import app.kleos.review.data.PlatformStatsDto
import app.kleos.review.data.ServerConfig
import app.kleos.review.testing.FakeKleosApi
import app.kleos.review.testing.InMemoryConfigStore
import app.kleos.review.testing.MainDispatcherRule
import app.kleos.review.testing.sampleClip
import app.kleos.review.ui.analytics.AnalyticsViewModel
import app.kleos.review.ui.analytics.PlatformOutcome
import app.kleos.review.ui.queue.QueueViewModel
import app.kleos.review.ui.settings.SettingsViewModel
import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class ScreenViewModelsTest {

    @get:Rule
    val main = MainDispatcherRule()

    private val api = FakeKleosApi()

    // --- queue -----------------------------------------------------------------

    @Test
    fun `queue loads pending clips`() {
        api.pendingResult = { listOf(sampleClip("a"), sampleClip("b")) }
        val state = QueueViewModel { api }.state.value
        assertFalse(state.loading)
        assertEquals(listOf("a", "b"), state.clips.map { it.videoId })
    }

    @Test
    fun `queue keeps the old list when a refresh fails`() {
        var fail = false
        api.pendingResult = { if (fail) throw IOException("down") else listOf(sampleClip("a")) }
        val vm = QueueViewModel { api }
        fail = true
        vm.refresh()
        assertEquals(listOf("a"), vm.state.value.clips.map { it.videoId })
        assertTrue(vm.state.value.error != null)
    }

    @Test
    fun `queue without settings asks for setup`() {
        assertTrue(QueueViewModel { null }.state.value.error!!.needsSetup)
    }

    @Test
    fun `queue flags a rejected token as a setup problem`() {
        api.pendingResult = { throw ApiException(401, "invalid or missing token") }
        assertTrue(QueueViewModel { api }.state.value.error!!.needsSetup)
    }

    // --- analytics -------------------------------------------------------------

    @Test
    fun `analytics exposes counts and platform outcomes busiest first`() {
        api.analyticsResult = {
            AnalyticsDto(
                clips = mapOf("pending" to 2, "approved" to 5),
                approvalRate = 0.5,
                platforms = mapOf("x" to PlatformStatsDto(1, 1), "facebook" to PlatformStatsDto(5, 0)),
            )
        }
        val state = AnalyticsViewModel { api }.state.value
        assertEquals(5, state.clipCount("approved"))
        assertEquals(0, state.clipCount("expired"))
        assertEquals(listOf("facebook", "x"), state.outcomes.map { it.name })
    }

    @Test
    fun `platform success rate is undefined with no attempts`() {
        assertNull(PlatformOutcome("x", 0, 0).successRate)
        assertEquals(0.75, PlatformOutcome("x", 3, 1).successRate!!, 0.0)
    }

    @Test
    fun `analytics failure is reported`() {
        api.analyticsResult = { throw IOException("down") }
        val state = AnalyticsViewModel { api }.state.value
        assertFalse(state.loading)
        assertTrue(state.error != null)
    }

    // --- settings --------------------------------------------------------------

    private val token = "k".repeat(32)

    @Test
    fun `settings refuses invalid input and saves nothing`() {
        val store = InMemoryConfigStore()
        val vm = SettingsViewModel(store) { api }
        vm.onUrlChange("http://public.example.com")
        vm.onTokenChange("short")
        vm.save()
        assertTrue(vm.state.value.urlError != null)
        assertTrue(vm.state.value.tokenError != null)
        assertNull(store.saved)
    }

    @Test
    fun `settings saves, clears the token field, and reports the connection`() {
        val store = InMemoryConfigStore()
        api.platformsResult = { listOf(PlatformDto("facebook", 7200), PlatformDto("x", 140)) }
        val vm = SettingsViewModel(store) { api }
        vm.onUrlChange("https://kleos.example.com/")
        vm.onTokenChange(token)
        vm.save()
        assertEquals(ServerConfig("https://kleos.example.com", token), store.saved)
        val state = vm.state.value
        assertEquals("", state.tokenInput)
        assertTrue(state.hasSavedToken)
        assertFalse(state.statusIsError)
        assertTrue(state.status!!.contains("Facebook, X"))
    }

    @Test
    fun `a blank token keeps the saved one when only the address changes`() {
        val store = InMemoryConfigStore(ServerConfig("https://old.example.com", token))
        val vm = SettingsViewModel(store) { api }
        assertEquals("https://old.example.com", vm.state.value.url)
        assertEquals("", vm.state.value.tokenInput)
        vm.onUrlChange("https://new.example.com")
        vm.save()
        assertEquals(ServerConfig("https://new.example.com", token), store.saved)
    }

    @Test
    fun `a failed connection test is reported but the settings stay saved`() {
        val store = InMemoryConfigStore()
        api.platformsResult = { throw ApiException(401, "invalid or missing token") }
        val vm = SettingsViewModel(store) { api }
        vm.onUrlChange("https://kleos.example.com")
        vm.onTokenChange(token)
        vm.save()
        assertTrue(store.saved != null)
        assertTrue(vm.state.value.statusIsError)
        assertTrue(vm.state.value.status!!.contains("token"))
    }
}
