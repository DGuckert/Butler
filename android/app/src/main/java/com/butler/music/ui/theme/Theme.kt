package com.butler.music.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * Butler's palette: a study at night, not a streaming app.
 * Warm ink instead of true black, brass instead of neon, oxblood as the
 * one warm accent reserved for "liked". Named so intent is obvious at
 * every call site.
 */
val Ink = Color(0xFF17140F)
val Surface = Color(0xFF221D15)
val SurfaceRaised = Color(0xFF2B241A)
val Parchment = Color(0xFFF0E6CF)
val Stone = Color(0xFF9B9484)
val Brass = Color(0xFFC89B3C)
val BrassDim = Color(0xFF8A7638)
val Oxblood = Color(0xFFA5453A)

private val ButlerColors = darkColorScheme(
    primary = Brass,
    onPrimary = Ink,
    secondary = Oxblood,
    onSecondary = Parchment,
    background = Ink,
    onBackground = Parchment,
    surface = Surface,
    onSurface = Parchment,
    surfaceVariant = SurfaceRaised,
    onSurfaceVariant = Stone,
    outline = Stone,
    error = Oxblood,
    onError = Parchment
)

@Composable
fun ButlerTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = ButlerColors,
        typography = ButlerTypography,
        content = content
    )
}
