package app.kleos.review.ui.review

import app.kleos.review.data.ApiException
import app.kleos.review.testing.FakeKleosApi
import app.kleos.review.testing.MainDispatcherRule
import app.kleos.review.testing.sampleClip
import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class ReviewViewModelTest {

    @get:Rule
    val main = MainDispatcherRule()

    private val api = FakeKleosApi()

    private fun viewModel(configured: Boolean = true) =
        ReviewViewModel({ if (configured) api else null }, "vid1")

    @Test
    fun `loads the clip with every available platform preselected`() {
        val state = viewModel().state.value
        assertEquals(ReviewPhase.Ready, state.phase)
        assertEquals("vid1", state.clip?.videoId)
        assertEquals(setOf("facebook", "instagram", "x"), state.selected)
        assertEquals("https://kleos.test/api/clips/vid1/stream", state.streamUrl)
        assertEquals("Bearer test", state.streamHeaders["Authorization"])
    }

    @Test
    fun `approve sends only the selected platforms, in server order`() {
        val vm = viewModel()
        vm.togglePlatform("instagram")
        vm.approve()
        assertEquals(listOf("vid1" to listOf("facebook", "x")), api.approveCalls)
        val phase = vm.state.value.phase as ReviewPhase.Approved
        assertEquals(listOf("facebook", "x"), phase.results.map { it.platform })
    }

    @Test
    fun `approve is impossible with nothing selected`() {
        val vm = viewModel()
        listOf("facebook", "instagram", "x").forEach(vm::togglePlatform)
        assertFalse(vm.state.value.canApprove)
        vm.approve()
        assertTrue(api.approveCalls.isEmpty())
    }

    @Test
    fun `unknown platforms cannot be toggled on`() {
        val vm = viewModel()
        vm.togglePlatform("tiktok")
        assertFalse("tiktok" in vm.state.value.selected)
    }

    @Test
    fun `reject calls the server and ends in the rejected phase`() {
        val vm = viewModel()
        vm.reject()
        assertEquals(listOf("vid1"), api.rejectCalls)
        assertEquals(ReviewPhase.Rejected, vm.state.value.phase)
    }

    @Test
    fun `a network failure keeps the clip reviewable with an error shown`() {
        api.approveResult = { _, _ -> throw IOException("timeout") }
        val vm = viewModel()
        vm.approve()
        val state = vm.state.value
        assertEquals(ReviewPhase.Ready, state.phase)
        assertTrue(state.actionError!!.message.contains("reach the server"))
        assertTrue(state.canApprove)
    }

    @Test
    fun `the kill switch keeps the clip reviewable`() {
        api.approveResult = { _, _ -> throw ApiException(423, "publishing is disabled") }
        val vm = viewModel()
        vm.approve()
        assertEquals(ReviewPhase.Ready, vm.state.value.phase)
    }

    @Test
    fun `a conflict means someone else decided - the clip becomes unavailable`() {
        api.rejectError = ApiException(409, "clip is not pending")
        val vm = viewModel()
        vm.reject()
        assertTrue(vm.state.value.phase is ReviewPhase.Unavailable)
        assertFalse(vm.state.value.canDecide)
    }

    @Test
    fun `a clip that is no longer pending cannot be reviewed`() {
        api.clipResult = { sampleClip(it, status = "expired") }
        val phase = viewModel().state.value.phase
        assertTrue(phase is ReviewPhase.Unavailable)
        assertTrue((phase as ReviewPhase.Unavailable).error.message.contains("expired"))
    }

    @Test
    fun `a load failure is shown as unavailable and can be retried`() {
        var fail = true
        api.clipResult = { if (fail) throw IOException("down") else sampleClip(it) }
        val vm = viewModel()
        assertTrue(vm.state.value.phase is ReviewPhase.Unavailable)
        fail = false
        vm.load()
        assertEquals(ReviewPhase.Ready, vm.state.value.phase)
    }

    @Test
    fun `without settings the screen asks for setup`() {
        val phase = viewModel(configured = false).state.value.phase as ReviewPhase.Unavailable
        assertTrue(phase.error.needsSetup)
    }
}
