package app.kleos.review.ui.queue

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.kleos.review.data.ApiProvider
import app.kleos.review.data.ClipDto
import app.kleos.review.ui.common.NotConfigured
import app.kleos.review.ui.common.UiError
import app.kleos.review.ui.common.toUiError
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class QueueUiState(
    val clips: List<ClipDto> = emptyList(),
    val loading: Boolean = true,
    val error: UiError? = null,
)

class QueueViewModel(private val provider: ApiProvider) : ViewModel() {

    private val _state = MutableStateFlow(QueueUiState())
    val state: StateFlow<QueueUiState> = _state.asStateFlow()

    private var inFlight: Job? = null

    init {
        refresh()
    }

    /** Reloads the queue. Keeps the current list on screen while loading. */
    fun refresh() {
        val api = provider.api()
        if (api == null) {
            _state.value = QueueUiState(loading = false, error = NotConfigured)
            return
        }
        inFlight?.cancel()
        _state.update { it.copy(loading = true, error = null) }
        inFlight = viewModelScope.launch {
            try {
                val clips = api.pending()
                _state.value = QueueUiState(clips = clips, loading = false)
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                _state.update { it.copy(loading = false, error = error.toUiError()) }
            }
        }
    }
}
