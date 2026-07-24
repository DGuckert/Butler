package com.butler.music.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.DownloadDone
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.layout.ContentScale
import com.butler.music.network.Song
import com.butler.music.ui.theme.Brass
import com.butler.music.ui.theme.Oxblood
import com.butler.music.ui.theme.Stone
import com.butler.music.ui.theme.SurfaceRaised

/**
 * A single catalog entry: artwork, title/artist, a like control, and the
 * running time set in monospace. Rows are separated by whitespace, not
 * dividers, so a long list stays calm instead of reading as a ledger.
 */
@Composable
fun SongRow(
    song: Song,
    onClick: () -> Unit,
    onToggleLike: (() -> Unit)? = null,
    downloadState: com.butler.music.data.DownloadState? = null,
    onToggleDownload: (() -> Unit)? = null,
    trailing: @Composable (() -> Unit)? = null,
    showDivider: Boolean = false
) {
    Column {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onClick)
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            SongArtwork(song.thumbnail, size = 52.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    song.title,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.titleMedium
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    song.artist,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.bodySmall,
                    color = Stone
                )
            }
            if (song.duration > 0) {
                Text(
                    formatDuration(song.duration),
                    style = MaterialTheme.typography.labelSmall,
                    color = Stone,
                    modifier = Modifier.padding(start = 8.dp)
                )
            }
            if (downloadState != null && onToggleDownload != null) {
                IconButton(onClick = onToggleDownload, modifier = Modifier.size(36.dp)) {
                    when (downloadState) {
                        com.butler.music.data.DownloadState.DOWNLOADING ->
                            CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp, color = Brass)
                        com.butler.music.data.DownloadState.DOWNLOADED ->
                            Icon(Icons.Filled.DownloadDone, contentDescription = "Downloaded, tap to remove", tint = Brass, modifier = Modifier.size(20.dp))
                        else ->
                            Icon(Icons.Filled.Download, contentDescription = "Download", tint = Stone, modifier = Modifier.size(20.dp))
                    }
                }
            }
            if (onToggleLike != null) {
                IconButton(onClick = onToggleLike, modifier = Modifier.size(36.dp)) {
                    Icon(
                        if (song.liked) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder,
                        contentDescription = "Like",
                        tint = if (song.liked) Oxblood else Stone,
                        modifier = Modifier.size(20.dp)
                    )
                }
            }
            trailing?.invoke()
        }
        if (showDivider) {
            HorizontalDivider(
                modifier = Modifier.padding(start = 80.dp),
                thickness = 0.6.dp,
                color = Stone.copy(alpha = 0.18f)
            )
        }
    }
}

@Composable
fun SongArtwork(url: String?, size: androidx.compose.ui.unit.Dp, shape: RoundedCornerShape = RoundedCornerShape(4.dp)) {
    if (url.isNullOrBlank()) {
        Box(
            Modifier
                .size(size)
                .clip(shape)
                .background(SurfaceRaised)
                .border(1.dp, Brass.copy(alpha = 0.25f), shape),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                Icons.Filled.MusicNote,
                contentDescription = null,
                tint = Brass.copy(alpha = 0.75f),
                modifier = Modifier.size(size / 2.2f)
            )
        }
    } else {
        AsyncImage(
            model = url,
            contentDescription = null,
            modifier = Modifier
                .size(size)
                .clip(shape)
        )
    }
}

/**
 * A single song as a square-art card, for horizontally-scrolling shelves
 * like Home's Recently Played / Recommended For You -- mirrors the card
 * grid on the web app rather than the flat rows used everywhere else,
 * since these sections are about browsing artwork, not scanning a list.
 */
@Composable
fun SongCard(song: Song, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Column(
        modifier
            .width(136.dp)
            .clickable(onClick = onClick)
    ) {
        SongArtwork(song.thumbnail, size = 136.dp, shape = RoundedCornerShape(8.dp))
        Spacer(Modifier.height(6.dp))
        Text(
            song.title,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
        Text(
            song.artist,
            style = MaterialTheme.typography.bodySmall,
            color = Stone,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@Composable
fun SongCardRow(songs: List<Song>, onClick: (Song) -> Unit) {
    LazyRow(
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        contentPadding = PaddingValues(horizontal = 16.dp)
    ) {
        items(songs, key = { it.youtubeId }) { song ->
            SongCard(song = song, onClick = { onClick(song) })
        }
    }
}

@Composable
fun SectionHeader(title: String, subtitle: String? = null, trailing: @Composable (() -> Unit)? = null) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 16.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column {
            Text(title, style = MaterialTheme.typography.headlineSmall)
            if (subtitle != null) {
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Stone)
            }
        }
        trailing?.invoke()
    }
}

@Composable
fun EmptyState(message: String, icon: androidx.compose.ui.graphics.vector.ImageVector = Icons.Filled.MusicNote) {
    Column(
        Modifier
            .fillMaxSize()
            .padding(top = 64.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Icon(icon, contentDescription = null, tint = Stone.copy(alpha = 0.4f), modifier = Modifier.size(40.dp))
        Spacer(Modifier.height(12.dp))
        Text(
            message,
            color = Stone,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.padding(horizontal = 40.dp),
            textAlign = androidx.compose.ui.text.style.TextAlign.Center
        )
    }
}

@Composable
fun LoadingState() {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator(color = Brass)
    }
}

@Composable
fun ErrorState(message: String, onRetry: (() -> Unit)? = null) {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(message, color = Oxblood, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        if (onRetry != null) {
            Spacer(Modifier.height(12.dp))
            OutlinedButton(onClick = onRetry) { Text("Retry") }
        }
    }
}

/** Fills its container, cropped, for banners/heroes rather than fixed-size rows. */
@Composable
fun HeroArtwork(url: String?, modifier: Modifier = Modifier) {
    if (url.isNullOrBlank()) {
        Box(modifier.background(SurfaceRaised))
    } else {
        AsyncImage(
            model = url,
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = modifier
        )
    }
}

/** "3:45" style formatting shared by song rows and the now playing screen. */
fun formatDuration(totalSeconds: Int): String {
    val s = totalSeconds.coerceAtLeast(0)
    val minutes = s / 60
    val seconds = s % 60
    return "%d:%02d".format(minutes, seconds)
}

fun formatDurationMs(ms: Long): String = formatDuration((ms / 1000).toInt())
