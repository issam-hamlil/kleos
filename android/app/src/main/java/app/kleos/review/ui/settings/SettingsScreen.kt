package app.kleos.review.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(viewModel: SettingsViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    Scaffold(topBar = { TopAppBar(title = { Text("Settings") }) }) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                "Connect to the Kleos server running on your PC. Use the tunnel's https address " +
                    "and the KLEOS_API_TOKEN value from the server's .env file.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedTextField(
                value = state.url,
                onValueChange = viewModel::onUrlChange,
                label = { Text("Server address") },
                placeholder = { Text("https://kleos.example.com") },
                singleLine = true,
                isError = state.urlError != null,
                supportingText = state.urlError?.let { error -> { Text(error) } },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Next),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = state.tokenInput,
                onValueChange = viewModel::onTokenChange,
                label = { Text("API token") },
                placeholder = {
                    Text(if (state.hasSavedToken) "Saved - leave blank to keep it" else "KLEOS_API_TOKEN")
                },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                isError = state.tokenError != null,
                supportingText = state.tokenError?.let { error -> { Text(error) } },
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Password,
                    autoCorrectEnabled = false,
                    imeAction = ImeAction.Done,
                ),
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = viewModel::save,
                enabled = !state.saving,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.saving) {
                    CircularProgressIndicator(
                        modifier = Modifier.padding(end = 8.dp).size(18.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                }
                Text(if (state.saving) "Checking connection..." else "Save and test")
            }
            state.status?.let { status ->
                Text(
                    status,
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (state.statusIsError) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}
