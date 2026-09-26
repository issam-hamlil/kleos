package app.kleos.review.ui.review

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Error
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kleos.review.data.PublishResultDto
import app.kleos.review.ui.common.ErrorPanel
import app.kleos.review.ui.common.Formatting
import app.kleos.review.ui.theme.LocalStatusColors

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReviewScreen(
    viewModel: ReviewViewModel,
    onBack: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var confirming by remember { mutableStateOf<Decision?>(null) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Review clip") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            when (val phase = state.phase) {
                ReviewPhase.Loading -> Centered { CircularProgressIndicator() }
                is ReviewPhase.Unavailable ->
                    ErrorPanel(phase.error, onRetry = viewModel::load, onOpenSettings = onOpenSettings)
                ReviewPhase.Ready, is ReviewPhase.Submitting ->
                    ReviewContent(state, viewModel, onConfirm = { confirming = it })
                is ReviewPhase.Approved -> ApprovedContent(phase.results, onBack)
                ReviewPhase.Rejected -> Outcome("Rejected. The clip was deleted and nothing was posted.", onBack)
            }
        }
    }

    confirming?.let { decision ->
        ConfirmDialog(
            decision = decision,
            platforms = state.platforms.map { it.name }.filter { it in state.selected },
            onConfirm = {
                confirming = null
                if (decision == Decision.APPROVE) viewModel.approve() else viewModel.reject()
            },
            onDismiss = { confirming = null },
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ReviewContent(state: ReviewUiState, viewModel: ReviewViewModel, onConfirm: (Decision) -> Unit) {
    val clip = state.clip ?: return
    val submitting = state.phase as? ReviewPhase.Submitting

    state.streamUrl?.let { ClipPlayer(url = it, headers = state.streamHeaders) }

    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(clip.title, style = MaterialTheme.typography.titleMedium)
        Text(
            "${Formatting.duration(clip.durationS)} · ${Formatting.expiresIn(clip.expiresAt)}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }

    Text("Publish to", style = MaterialTheme.typography.labelLarge)
    if (state.platforms.isEmpty()) {
        Text(
            "No platforms are enabled on the server. Add credentials there to publish.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        state.platforms.forEach { platform ->
            val selected = platform.name in state.selected
            FilterChip(
                selected = selected,
                onClick = { viewModel.togglePlatform(platform.name) },
                enabled = state.canDecide,
                label = { Text(Formatting.platformLabel(platform.name)) },
                leadingIcon = if (selected) {
                    { Icon(Icons.Filled.Check, contentDescription = null, modifier = Modifier.size(18.dp)) }
                } else {
                    null
                },
            )
        }
    }

    state.actionError?.let {
        Text(it.message, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
    }

    if (submitting != null) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            CircularProgressIndicator(modifier = Modifier.size(24.dp))
            Text(
                if (submitting.decision == Decision.APPROVE) {
                    "Publishing... Instagram can take a few minutes to process video."
                } else {
                    "Rejecting..."
                },
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }

    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
        OutlinedButton(
            onClick = { onConfirm(Decision.REJECT) },
            enabled = state.canDecide,
            modifier = Modifier.weight(1f),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
        ) {
            Icon(Icons.Filled.Close, contentDescription = null)
            Text("Reject", modifier = Modifier.padding(start = 8.dp))
        }
        Button(
            onClick = { onConfirm(Decision.APPROVE) },
            enabled = state.canApprove,
            modifier = Modifier.weight(1f),
        ) {
            Icon(Icons.Filled.Check, contentDescription = null)
            Text("Approve", modifier = Modifier.padding(start = 8.dp))
        }
    }
}

@Composable
private fun ApprovedContent(results: List<PublishResultDto>, onBack: () -> Unit) {
    val status = LocalStatusColors.current
    Text("Publish results", style = MaterialTheme.typography.titleMedium)
    results.forEach { result ->
        Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            // Status is always icon + words, never colour alone.
            Icon(
                if (result.ok) Icons.Filled.CheckCircle else Icons.Filled.Error,
                contentDescription = if (result.ok) "Published" else "Failed",
                tint = if (result.ok) status.good else status.critical,
            )
            Column {
                Text(
                    "${Formatting.platformLabel(result.platform)}: ${if (result.ok) "published" else "failed"}",
                    style = MaterialTheme.typography.bodyLarge,
                )
                if (!result.ok && result.error.isNotBlank()) {
                    Text(
                        result.error,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
    Button(onClick = onBack, modifier = Modifier.fillMaxWidth()) { Text("Back to queue") }
}

@Composable
private fun Outcome(message: String, onBack: () -> Unit) {
    Text(message, style = MaterialTheme.typography.bodyLarge)
    Button(onClick = onBack, modifier = Modifier.fillMaxWidth()) { Text("Back to queue") }
}

@Composable
private fun ConfirmDialog(
    decision: Decision,
    platforms: List<String>,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    val approving = decision == Decision.APPROVE
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (approving) "Publish this clip?" else "Reject this clip?") },
        text = {
            Text(
                if (approving) {
                    "It will be posted publicly to ${platforms.joinToString { Formatting.platformLabel(it) }}."
                } else {
                    "The clip will be deleted and never posted. This can't be undone."
                },
            )
        },
        confirmButton = {
            TextButton(onClick = onConfirm) { Text(if (approving) "Publish" else "Reject") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun Centered(content: @Composable () -> Unit) {
    Box(Modifier.fillMaxWidth().padding(vertical = 48.dp), contentAlignment = Alignment.Center) { content() }
}
