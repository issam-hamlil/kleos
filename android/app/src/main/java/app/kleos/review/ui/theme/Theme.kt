package app.kleos.review.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

private val Pitch = Color(0xFF0F3D2E)
private val PitchLight = Color(0xFF7EE2A8)

private val LightColors = lightColorScheme(
    primary = Pitch,
    onPrimary = Color.White,
    secondary = Color(0xFF3B6352),
)

private val DarkColors = darkColorScheme(
    primary = PitchLight,
    onPrimary = Color(0xFF00391F),
    secondary = Color(0xFFA3CFB8),
)

/**
 * Status colours are reserved for outcomes (published / failed) and never
 * reused as decoration. They always appear with an icon and a label.
 * Separate light and dark steps, each chosen for contrast on its own surface.
 */
@Immutable
data class StatusColors(val good: Color, val critical: Color)

private val LightStatus = StatusColors(good = Color(0xFF1B7F4B), critical = Color(0xFFB3261E))
private val DarkStatus = StatusColors(good = Color(0xFF6FD79B), critical = Color(0xFFF2B8B5))

val LocalStatusColors = staticCompositionLocalOf { LightStatus }

@Composable
fun KleosTheme(darkTheme: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val colors: ColorScheme = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }
        darkTheme -> DarkColors
        else -> LightColors
    }
    androidx.compose.runtime.CompositionLocalProvider(
        LocalStatusColors provides if (darkTheme) DarkStatus else LightStatus,
    ) {
        MaterialTheme(colorScheme = colors, content = content)
    }
}
