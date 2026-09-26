package app.kleos.review.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.kleos.review.data.ConfigStore
import app.kleos.review.data.KleosApi
import app.kleos.review.data.ServerConfig
import app.kleos.review.data.ServerConfigValidator
import app.kleos.review.data.Validation
import app.kleos.review.ui.common.Formatting
import app.kleos.review.ui.common.toUiError
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SettingsUiState(
    val url: String = "",
    /** What the operator is typing. The saved token is never read back into the UI. */
    val tokenInput: String = "",
    val hasSavedToken: Boolean = false,
    val saving: Boolean = false,
    val urlError: String? = null,
    val tokenError: String? = null,
    val status: String? = null,
    val statusIsError: Boolean = false,
)

class SettingsViewModel(
    private val store: ConfigStore,
    private val apiFor: (ServerConfig) -> KleosApi,
) : ViewModel() {

    private val _state = MutableStateFlow(initialState())
    val state: StateFlow<SettingsUiState> = _state.asStateFlow()

    private fun initialState(): SettingsUiState {
        val saved = store.load()
        return SettingsUiState(url = saved?.baseUrl.orEmpty(), hasSavedToken = saved != null)
    }

    fun onUrlChange(value: String) = _state.update { it.copy(url = value, urlError = null, status = null) }

    fun onTokenChange(value: String) = _state.update { it.copy(tokenInput = value, tokenError = null, status = null) }

    /** Validates, saves, then checks the server actually accepts the settings. */
    fun save() {
        val current = _state.value
        val url = ServerConfigValidator.url(current.url)
        val token = resolveToken(current)
        if (url is Validation.Invalid || token is Validation.Invalid) {
            _state.update {
                it.copy(
                    urlError = (url as? Validation.Invalid)?.reason,
                    tokenError = (token as? Validation.Invalid)?.reason,
                )
            }
            return
        }
        val config = ServerConfig((url as Validation.Valid).value, (token as Validation.Valid).value)
        store.save(config)
        _state.update {
            it.copy(url = config.baseUrl, tokenInput = "", hasSavedToken = true, saving = true, status = null)
        }
        viewModelScope.launch { testConnection(config) }
    }

    /** A blank token field keeps the saved token, so changing only the address is easy. */
    private fun resolveToken(current: SettingsUiState): Validation {
        if (current.tokenInput.isBlank() && current.hasSavedToken) {
            val saved = store.load() ?: return Validation.Invalid("Enter the API token")
            return Validation.Valid(saved.token)
        }
        return ServerConfigValidator.token(current.tokenInput)
    }

    private suspend fun testConnection(config: ServerConfig) {
        try {
            val platforms = apiFor(config).platforms()
            val names = platforms.joinToString { Formatting.platformLabel(it.name) }
            val message = if (platforms.isEmpty()) {
                "Saved. Connected, but no platforms are enabled on the server."
            } else {
                "Saved. Connected - ready to publish to $names."
            }
            _state.update { it.copy(saving = false, status = message, statusIsError = false) }
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            _state.update {
                it.copy(saving = false, status = "Saved, but " + error.toUiError().message.lowercaseFirst(), statusIsError = true)
            }
        }
    }

    private fun String.lowercaseFirst(): String = replaceFirstChar { it.lowercase() }
}
