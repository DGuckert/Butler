package com.butler.music.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.butler.music.playback.PlayerController
import com.butler.music.ui.theme.Brass
import com.butler.music.ui.theme.Ink
import com.butler.music.ui.theme.Oxblood
import com.butler.music.ui.theme.Stone
import com.butler.music.ui.theme.SurfaceRaised

/**
 * The one place Butler spends its "one real risk": the artwork spins like
 * a record on a turntable while a song plays, and settles when it's
 * paused. Everywhere else in the app stays quiet on purpose.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NowPlayingSheet(player: PlayerController, onToggleLike: (com.butler.music.network.Song) -> Unit, onDismiss: () -> Unit) {
    val state by player.state.collectAsStateWithLifecycle()
    val song = state.currentSong

    var userSeeking by remember { mutableStateOf(false) }
    var dragPositionMs by remember { mutableLongStateOf(0L) }
    val positionMs = if (userSeeking) dragPositionMs else state.positionMs

    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Ink) {
        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 28.dp)
                .padding(bottom = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            if (song == null) {
                Text("Nothing playing", color = Stone, modifier = Modifier.padding(vertical = 48.dp))
            } else {
                Spacer(Modifier.height(4.dp))
                VinylArtwork(url = song.thumbnail, spinning = state.isPlaying)
                Spacer(Modifier.height(28.dp))
                Text(
                    song.title,
                    style = MaterialTheme.typography.titleLarge,
                    textAlign = TextAlign.Center,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    song.artist,
                    style = MaterialTheme.typography.bodyMedium,
                    color = Stone
                )
                Spacer(Modifier.height(20.dp))

                val durationMs = state.durationMs.coerceAtLeast(1L)
                Slider(
                    value = positionMs.coerceIn(0L, durationMs).toFloat(),
                    onValueChange = { userSeeking = true; dragPositionMs = it.toLong() },
                    onValueChangeFinished = { player.seekTo(positionMs); userSeeking = false },
                    valueRange = 0f..durationMs.toFloat(),
                    colors = SliderDefaults.colors(
                        thumbColor = Brass,
                        activeTrackColor = Brass,
                        inactiveTrackColor = SurfaceRaised
                    )
                )
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatDurationMs(positionMs), style = MaterialTheme.typography.labelSmall, color = Stone)
                    Text(formatDurationMs(state.durationMs), style = MaterialTheme.typography.labelSmall, color = Stone)
                }

                Spacer(Modifier.height(12.dp))

                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = { onToggleLike(song) }, modifier = Modifier.size(44.dp)) {
                        Icon(
                            if (song.liked) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder,
                            contentDescription = "Like",
                            tint = if (song.liked) Oxblood else Stone
                        )
                    }
                    Spacer(Modifier.weight(1f))
                    IconButton(onClick = { player.previous() }) {
                        Icon(Icons.Filled.SkipPrevious, contentDescription = "Previous", modifier = Modifier.size(34.dp))
                    }
                    Spacer(Modifier.width(12.dp))
                    FilledIconButton(
                        onClick = { player.playPause() },
                        modifier = Modifier.size(62.dp),
                        colors = IconButtonDefaults.filledIconButtonColors(containerColor = Brass, contentColor = Ink)
                    ) {
                        Icon(
                            if (state.isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                            contentDescription = "Play or pause",
                            modifier = Modifier.size(30.dp)
                        )
                    }
                    Spacer(Modifier.width(12.dp))
                    IconButton(onClick = { player.next() }) {
                        Icon(Icons.Filled.SkipNext, contentDescription = "Next", modifier = Modifier.size(34.dp))
                    }
                    Spacer(Modifier.weight(1f))
                    Spacer(Modifier.size(44.dp))
                }

                if (state.queue.size > 1) {
                    Spacer(Modifier.height(28.dp))
                    Text(
                        "UP NEXT",
                        style = MaterialTheme.typography.labelLarge,
                        color = Stone,
                        modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp)
                    )
                    Column(Modifier.fillMaxWidth()) {
                        state.queue.drop(state.currentIndex + 1).take(5).forEach { upNext ->
                            Row(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                                Text(
                                    upNext.title,
                                    style = MaterialTheme.typography.bodySmall,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f)
                                )
                                Spacer(Modifier.width(8.dp))
                                Text(
                                    upNext.artist,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = Stone,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun VinylArtwork(url: String?, spinning: Boolean) {
    val infinite = rememberInfiniteTransition(label = "vinyl")
    val angle by infinite.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(6000, easing = LinearEasing)),
        label = "vinylAngle"
    )
    val size = 240.dp

    Box(modifier = Modifier.size(size), contentAlignment = Alignment.Center) {
        Box(
            Modifier
                .size(size)
                .rotate(if (spinning) angle else 0f)
        ) {
            SongArtwork(url, size = size, shape = androidx.compose.foundation.shape.RoundedCornerShape(size))
            // Groove rings + label hole, drawn over the artwork so any
            // image reads as a record rather than a plain circular crop.
            Canvas(modifier = Modifier.matchParentSize()) {
                val center = Offset(this.size.width / 2f, this.size.height / 2f)
                val maxRadius = this.size.minDimension / 2f
                val grooveColor = Color.Black.copy(alpha = 0.18f)
                var r = maxRadius * 0.42f
                while (r < maxRadius * 0.98f) {
                    drawCircle(color = grooveColor, radius = r, center = center, style = androidx.compose.ui.graphics.drawscope.Stroke(width = 1f))
                    r += maxRadius * 0.07f
                }
                drawCircle(color = Color.Black.copy(alpha = 0.75f), radius = maxRadius * 0.16f, center = center)
                drawCircle(color = Brass, radius = maxRadius * 0.16f, center = center, style = androidx.compose.ui.graphics.drawscope.Stroke(width = 2f))
                drawCircle(color = Ink, radius = maxRadius * 0.035f, center = center)
            }
        }
    }
}
