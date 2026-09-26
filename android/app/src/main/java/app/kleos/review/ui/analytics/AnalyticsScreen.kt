package app.kleos.review.ui.analytics

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.PauseCircle
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.kleos.review.data.HistoryEntryDto
import app.kleos.review.ui.common.EmptyState
import app.kleos.review.ui.common.ErrorPanel
import app.kleos.review.ui.common.Formatting
import app.kleos.review.ui.theme.LocalStatusColors

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AnalyticsScreen(viewModel: AnalyticsViewModel, onOpenSettings: () -> Unit) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { viewModel.refresh() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Analytics") },
                actions = {
                    IconButton(onClick = viewModel::refresh) {
                        Icon(Icons.Filled.Refresh, contentDescription = "Refresh")
                    }
                },
            )
        },
    ) { padding ->
        PullToRefreshBox(
            isRefreshing = state.loading,
            onRefresh = viewModel::refresh,
            modifier = Modifier.fillMaxSize().padding(padding),
        ) {
            LazyColumn(
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                modifier = Modifier.fillMaxSize(),
            ) {
                state.error?.let { error ->
                    item { ErrorPanel(error, onRetry = viewModel::refresh, onOpenSettings = onOpenSettings) }
                }
                state.analytics?.let { analytics ->
                    item { PublishingStatus(analytics.publishingEnabled) }
                    item { DecisionTiles(state) }
                    item {
                        TileRow(
                            "Approval rate" to Formatting.percent(analytics.approvalRate),
                            "Avg. review time" to Formatting.reviewTime(analytics.avgReviewMinutes),
                        )
                    }
                    item { SectionTitle("Publishing by platform") }
                    if (state.outcomes.isEmpty()) {
                        item { Muted("Nothing published yet.") }
                    }
                    items(state.outcomes, key = { it.name }) { PlatformRow(it) }
                    item { SectionTitle("Recent activity") }
                    if (state.history.isEmpty()) {
                        item { EmptyState("No activity yet", "Approved clips and their results show up here.") }
                    }
                    items(state.history, key = { "${it.videoId}-${it.platform}" }) { HistoryRow(it) }
                }
            }
        }
    }
}

@Composable
private fun PublishingStatus(enabled: Boolean) {
    val status = LocalStatusColors.current
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Icon(
            if (enabled) Icons.Filled.PlayCircle else Icons.Filled.PauseCircle,
            contentDescription = null,
            tint = if (enabled) status.good else status.critical,
        )
        Text(
            if (enabled) "Publishing is enabled on the server" else "Publishing is paused by the kill switch",
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun DecisionTiles(state: AnalyticsUiState) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        TileRow(
            "Waiting" to state.clipCount("pending").toString(),
            "Approved" to state.clipCount("approved").toString(),
        )
        TileRow(
            "Rejected" to state.clipCount("rejected").toString(),
            "Expired" to state.clipCount("expired").toString(),
        )
    }
}

/** Headline numbers as stat tiles: a single value per metric needs no chart. */
@Composable
private fun TileRow(first: Pair<String, String>, second: Pair<String, String>) {
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        StatTile(first.first, first.second, Modifier.weight(1f))
        StatTile(second.first, second.second, Modifier.weight(1f))
    }
}

@Composable
private fun StatTile(label: String, value: String, modifier: Modifier = Modifier) {
    Card(modifier = modifier) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(value, style = MaterialTheme.typography.headlineMedium)
        }
    }
}

/**
 * Published vs failed for one platform: counts as text, plus a two-segment
 * meter. Segments use the reserved status colours, separated by a 2dp gap,
 * and the whole row reads out as words for screen readers.
 */
@Composable
private fun PlatformRow(outcome: PlatformOutcome) {
    val status = LocalStatusColors.current
    val label = Formatting.platformLabel(outcome.name)
    Column(
        verticalArrangement = Arrangement.spacedBy(6.dp),
        modifier = Modifier.semantics {
            contentDescription = "$label: ${outcome.published} published, ${outcome.failed} failed"
        },
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
            Icon(Icons.Filled.CheckCircle, null, tint = status.good, modifier = Modifier.size(16.dp))
            Text(" ${outcome.published} published", style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.width(12.dp))
            Icon(Icons.Filled.Error, null, tint = status.critical, modifier = Modifier.size(16.dp))
            Text(" ${outcome.failed} failed", style = MaterialTheme.typography.bodySmall)
        }
        if (outcome.attempts > 0) {
            Row(
                modifier = Modifier.fillMaxWidth().height(8.dp),
                horizontalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                if (outcome.published > 0) {
                    MeterSegment(outcome.published.toFloat(), status.good)
                }
                if (outcome.failed > 0) {
                    MeterSegment(outcome.failed.toFloat(), status.critical)
                }
            }
            Text(
                "${Formatting.percent(outcome.successRate)} succeeded",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun androidx.compose.foundation.layout.RowScope.MeterSegment(
    weight: Float,
    color: androidx.compose.ui.graphics.Color,
) {
    Box(
        Modifier
            .weight(weight)
            .fillMaxHeight()
            .clip(RoundedCornerShape(4.dp))
            .background(color),
    )
}

@Composable
private fun HistoryRow(entry: HistoryEntryDto) {
    val status = LocalStatusColors.current
    Column {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Icon(
                if (entry.ok) Icons.Filled.CheckCircle else Icons.Filled.Error,
                contentDescription = if (entry.ok) "Published" else "Failed",
                tint = if (entry.ok) status.good else status.critical,
                modifier = Modifier.size(20.dp),
            )
            Column(Modifier.weight(1f)) {
                Text(entry.title, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    "${Formatting.platformLabel(entry.platform)} · ${Formatting.ago(entry.at)}" +
                        if (!entry.ok && entry.error.isNotBlank()) " · ${entry.error}" else "",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        HorizontalDivider(Modifier.padding(top = 12.dp))
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 8.dp))
}

@Composable
private fun Muted(text: String) {
    Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
}
