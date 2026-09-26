package app.kleos.review.ui.review

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.kleos.review.data.ApiException
import app.kleos.review.data.ApiProvider
import app.kleos.review.data.ClipDto
import app.kleos.review.data.KleosApi
import app.kleos.review.data.PlatformDto
import app.kleos.review.data.PublishResultDto
import app.kleos.review.ui.common.NotConfigured
import app.kleos.review.ui.common.UiError
import app.kleos.review.ui.common.toUiError
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class Decision { APPROVE, REJECT }

sealed interface ReviewPhase {
    data object Loading : ReviewPhase
    data object Ready : ReviewPhase
    data class Submitting(val decision: Decision) : ReviewPhase
    data class Approved(val results: List<PublishResultDto>) : ReviewPhase
    data object Rejected : ReviewPhase

    /** The clip can't be reviewed: gone, decided elsewhere, or the server is unreachable. */
    data class Unavailable(val error: UiError) : ReviewPhase
}

data class ReviewUiState(
    val phase: ReviewPhase = ReviewPhase.Loading,
    val clip: ClipDto? = null,
    val platforms: List<PlatformDto> = emptyList(),
    val selected: Set<String> = emptySet(),
    val streamUrl: String? = null,
    val streamHeaders: Map<String, String> = emptyMap(),
    /** A failed approve/reject that left the clip still reviewable (e.g. network blip). */
    val actionError: UiError? = null,
) {
    val canDecide: Boolean get() = phase == ReviewPhase.Ready
    val canApprove: Boolean get() = canDecide && selected.isNotEmpty()
}

class ReviewViewModel(
    private val provider: ApiProvider,
    private val videoId: String,
) : ViewModel() {

    private val _state = MutableStateFlow(ReviewUiState())
    val state: StateFlow<ReviewUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        val api = provider.api() ?: return unavailable(NotConfigured)
        _state.update { it.copy(phase = ReviewPhase.Loading, actionError = null) }
        viewModelScope.launch {
            try {
                val (clip, platforms) = coroutineScope {
                    val clip = async { api.clip(videoId) }
                    val platforms = async { api.platforms() }
                    clip.await() to platforms.await()
                }
                _state.value = readyState(api, clip, platforms)
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                unavailable(error.toUiError())
            }
        }
    }

    /** Every available platform starts selected; the operator unticks what they don't want. */
    private fun readyState(api: KleosApi, clip: ClipDto, platforms: List<PlatformDto>) =
        if (clip.status != "pending") {
            ReviewUiState(
                phase = ReviewPhase.Unavailable(UiError("This clip is already ${clip.status}.")),
                clip = clip,
            )
        } else {
            ReviewUiState(
                phase = ReviewPhase.Ready,
                clip = clip,
                platforms = platforms,
                selected = platforms.map { it.name }.toSet(),
                streamUrl = api.streamUrl(videoId),
                streamHeaders = api.authHeaders,
            )
        }

    fun togglePlatform(name: String) {
        _state.update { current ->
            if (!current.canDecide || current.platforms.none { it.name == name }) return@update current
            val selected = if (name in current.selected) current.selected - name else current.selected + name
            current.copy(selected = selected, actionError = null)
        }
    }

    fun approve() {
        val snapshot = _state.value
        if (!snapshot.canApprove) return
        // Keep the server's platform order so results read the same way as the chips.
        val chosen = snapshot.platforms.map { it.name }.filter { it in snapshot.selected }
        submit(Decision.APPROVE) { api ->
            ReviewPhase.Approved(api.approve(videoId, chosen).results)
        }
    }

    fun reject() {
        if (!_state.value.canDecide) return
        submit(Decision.REJECT) { api ->
            api.reject(videoId)
            ReviewPhase.Rejected
        }
    }

    private fun submit(decision: Decision, action: suspend (KleosApi) -> ReviewPhase) {
        val api = provider.api() ?: return unavailable(NotConfigured)
        _state.update { it.copy(phase = ReviewPhase.Submitting(decision), actionError = null) }
        viewModelScope.launch {
            try {
                val outcome = action(api)
                _state.update { it.copy(phase = outcome) }
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                onSubmitFailed(error)
            }
        }
    }

    /**
     * A conflict or missing clip is final - someone else decided it, or it expired.
     * Anything else (network, kill switch) leaves the clip reviewable so the operator can retry.
     */
    private fun onSubmitFailed(error: Exception) {
        val final = error is ApiException && (error.status == 409 || error.status == 404)
        if (final) {
            unavailable(error.toUiError())
        } else {
            _state.update { it.copy(phase = ReviewPhase.Ready, actionError = error.toUiError()) }
        }
    }

    private fun unavailable(error: UiError) {
        _state.update { it.copy(phase = ReviewPhase.Unavailable(error)) }
    }
}
