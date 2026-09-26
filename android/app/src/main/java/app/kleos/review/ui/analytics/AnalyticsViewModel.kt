package app.kleos.review.ui.analytics

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.kleos.review.data.AnalyticsDto
import app.kleos.review.data.ApiProvider
import app.kleos.review.data.HistoryEntryDto
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

/** One platform's publish outcomes, with the success share precomputed for display. */
data class PlatformOutcome(val name: String, val published: Int, val failed: Int) {
    val attempts: Int get() = published + failed
    val successRate: Double? get() = if (attempts == 0) null else published.toDouble() / attempts
}

data class AnalyticsUiState(
    val analytics: AnalyticsDto? = null,
    val history: List<HistoryEntryDto> = emptyList(),
    val loading: Boolean = true,
    val error: UiError? = null,
) {
    /** Platforms sorted by volume, busiest first. */
    val outcomes: List<PlatformOutcome>
        get() = analytics?.platforms.orEmpty()
            .map { (name, stats) -> PlatformOutcome(name, stats.published, stats.failed) }
            .sortedByDescending { it.attempts }

    fun clipCount(status: String): Int = analytics?.clips?.get(status) ?: 0
}

class AnalyticsViewModel(private val provider: ApiProvider) : ViewModel() {

    private val _state = MutableStateFlow(AnalyticsUiState())
    val state: StateFlow<AnalyticsUiState> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        val api = provider.api()
        if (api == null) {
            _state.value = AnalyticsUiState(loading = false, error = NotConfigured)
            return
        }
        _state.update { it.copy(loading = true, error = null) }
        viewModelScope.launch {
            try {
                val (analytics, history) = coroutineScope {
                    val analytics = async { api.analytics() }
                    val history = async { api.history(HISTORY_LIMIT) }
                    analytics.await() to history.await()
                }
                _state.value = AnalyticsUiState(analytics = analytics, history = history, loading = false)
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                _state.update { it.copy(loading = false, error = error.toUiError()) }
            }
        }
    }

    private companion object {
        const val HISTORY_LIMIT = 30
    }
}
