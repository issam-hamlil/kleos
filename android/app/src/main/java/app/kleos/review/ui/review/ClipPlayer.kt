package app.kleos.review.ui.review

import androidx.annotation.OptIn
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView

/**
 * Plays the pending clip straight from the Kleos server.
 *
 * The stream endpoint needs the bearer token, so every request the player
 * makes - including Range requests when seeking - carries the auth headers.
 */
@OptIn(UnstableApi::class)
@Composable
fun ClipPlayer(url: String, headers: Map<String, String>, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val player = remember(url) {
        val dataSource = DefaultHttpDataSource.Factory().setDefaultRequestProperties(headers)
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(DefaultMediaSourceFactory(dataSource))
            .build()
            .apply {
                setMediaItem(MediaItem.fromUri(url))
                prepare()
            }
    }
    DisposableEffect(player) {
        onDispose { player.release() }
    }
    AndroidView(
        factory = { viewContext -> PlayerView(viewContext).apply { this.player = player } },
        modifier = modifier.fillMaxWidth().aspectRatio(16f / 9f),
    )
}
