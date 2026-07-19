package com.butler.music.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.butler.music.network.Playlist
import com.butler.music.network.Song
import com.butler.music.ui.theme.Brass
import com.butler.music.ui.theme.Ink
import com.butler.music.ui.theme.Oxblood
import com.butler.music.ui.theme.Stone
import com.butler.music.ui.theme.Surface as ButlerSurface
import com.butler.music.ui.theme.SurfaceRaised

@Composable
fun HomeTab(vm: MainViewModel, onSongClick: (List<Song>, Song) -> Unit, onToggleLike: (Song) -> Unit) {
    val dailyMix by vm.dailyMix.collectAsStateWithLifecycle()
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            when (val state = dailyMix) {
                is LoadState.Loaded -> if (state.value.isNotEmpty()) {
                    DailyMixHero(
                        first = state.value.first(),
                        count = state.value.size,
                        onPlay = { onSongClick(state.value, state.value.first()) },
                        onRegenerate = { vm.regenerateDailyMix() }
                    )
                } else {
                    SectionHeader(
                        "Daily Mix",
                        trailing = {
                            IconButton(onClick = { vm.regenerateDailyMix() }) {
                                Icon(Icons.Filled.Refresh, contentDescription = "Regenerate", tint = Stone)
                            }
                        }
                    )
                }
                else -> SectionHeader("Daily Mix")
            }
        }
        when (val state = dailyMix) {
            is LoadState.Loading -> item { LoadingState() }
            is LoadState.Failed -> item { ErrorState(state.message, onRetry = vm::loadDailyMix) }
            is LoadState.Loaded -> if (state.value.isEmpty()) {
                item { EmptyState("No Daily Mix yet. Listen to a few songs first.") }
            } else {
                items(state.value.drop(1), key = { it.youtubeId }) { song ->
                    SongRow(
                        song = song,
                        onClick = { onSongClick(state.value, song) },
                        onToggleLike = { onToggleLike(song) }
                    )
                }
            }
        }
    }
}

/**
 * A record-sleeve hero for the top of Home: the first track's artwork
 * fills the width, darkened, with the mix name over it in the display
 * face. Everywhere else in the app is a plain list; this is the one
 * screen that earns a bigger moment.
 */
@Composable
private fun DailyMixHero(first: Song, count: Int, onPlay: () -> Unit, onRegenerate: () -> Unit) {
    Box(
        Modifier
            .fillMaxWidth()
            .height(180.dp)
            .clickable(onClick = onPlay)
    ) {
        HeroArtwork(first.thumbnail, modifier = Modifier.matchParentSize())
        Box(
            Modifier
                .matchParentSize()
                .background(
                    androidx.compose.ui.graphics.Brush.verticalGradient(
                        colors = listOf(Ink.copy(alpha = 0.25f), Ink.copy(alpha = 0.92f))
                    )
                )
        )
        Column(
            Modifier
                .align(Alignment.BottomStart)
                // Reserve room for the play button sitting in the same
                // corner so the wrapped text never runs under it.
                .padding(start = 20.dp, top = 20.dp, bottom = 20.dp, end = 96.dp)
        ) {
            Text(
                "DAILY MIX",
                style = MaterialTheme.typography.labelLarge,
                color = Brass
            )
            Text(
                "$count songs, picked for you",
                style = MaterialTheme.typography.titleLarge,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
        }
        Row(
            Modifier.align(Alignment.TopEnd).padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(onClick = onRegenerate) {
                Icon(Icons.Filled.Refresh, contentDescription = "Regenerate", tint = androidx.compose.ui.graphics.Color.White)
            }
        }
        FilledIconButton(
            onClick = onPlay,
            modifier = Modifier.align(Alignment.BottomEnd).padding(20.dp).size(52.dp),
            colors = IconButtonDefaults.filledIconButtonColors(containerColor = Brass, contentColor = Ink)
        ) {
            Icon(Icons.Filled.PlayArrow, contentDescription = "Play Daily Mix")
        }
    }
}

/**
 * "Your Library" the way Spotify structures it: one screen, filter chips
 * instead of separate tabs for playlists vs liked songs vs downloaded
 * songs. Liked Songs gets a pinned row at the top, same as Spotify pins
 * it first, since it is functionally a playlist users open constantly.
 */
private enum class LibraryFilter(val label: String) {
    ALL("All"), PLAYLISTS("Playlists"), SONGS("Songs")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LibraryTab(
    vm: MainViewModel,
    navController: NavHostController,
    onSongClick: (List<Song>, Song) -> Unit,
    onToggleLike: (Song) -> Unit
) {
    val library by vm.library.collectAsStateWithLifecycle()
    val liked by vm.liked.collectAsStateWithLifecycle()
    val playlists by vm.playlists.collectAsStateWithLifecycle()
    var filter by remember { mutableStateOf(LibraryFilter.ALL) }
    var showCreate by remember { mutableStateOf(false) }
    var newName by remember { mutableStateOf("") }

    val likedCount = (liked as? LoadState.Loaded)?.value?.size ?: 0
    val showPlaylists = filter == LibraryFilter.ALL || filter == LibraryFilter.PLAYLISTS
    val showSongs = filter == LibraryFilter.ALL || filter == LibraryFilter.SONGS

    Column(Modifier.fillMaxSize()) {
        SectionHeader(
            "Your Library",
            trailing = {
                IconButton(onClick = { showCreate = true }) {
                    Icon(Icons.Filled.Add, contentDescription = "New playlist", tint = Brass)
                }
            }
        )
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(bottom = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            LibraryFilter.entries.forEach { f ->
                FilterChip(
                    selected = filter == f,
                    onClick = { filter = f },
                    label = { Text(f.label) },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = Brass,
                        selectedLabelColor = Ink,
                        containerColor = SurfaceRaised,
                        labelColor = Stone
                    ),
                    border = null
                )
            }
        }

        LazyColumn {
            if (showPlaylists) {
                item {
                    LikedSongsRow(count = likedCount) { navController.navigate("liked") }
                }
                when (val state = playlists) {
                    is LoadState.Loading -> item { LoadingState() }
                    is LoadState.Failed -> item { ErrorState(state.message, onRetry = vm::loadPlaylists) }
                    is LoadState.Loaded -> items(state.value, key = { "pl-${it.id}" }) { playlist ->
                        PlaylistRow(playlist) { navController.navigate("playlist/${playlist.id}") }
                    }
                }
            }
            if (showSongs) {
                when (val state = library) {
                    is LoadState.Loading -> item { LoadingState() }
                    is LoadState.Failed -> item { ErrorState(state.message, onRetry = vm::loadLibrary) }
                    is LoadState.Loaded -> if (state.value.isEmpty() && !showPlaylists) {
                        item { EmptyState("Nothing downloaded yet. Search for a song to add it.") }
                    } else {
                        items(state.value, key = { "song-${it.youtubeId}" }) { song ->
                            SongRow(
                                song = song,
                                onClick = { onSongClick(state.value, song) },
                                onToggleLike = { onToggleLike(song) }
                            )
                        }
                    }
                }
            }
        }
    }

    if (showCreate) {
        AlertDialog(
            onDismissRequest = { showCreate = false },
            title = { Text("New playlist") },
            text = {
                OutlinedTextField(value = newName, onValueChange = { newName = it }, singleLine = true, placeholder = { Text("Name") })
            },
            confirmButton = {
                TextButton(onClick = {
                    if (newName.isNotBlank()) vm.createPlaylist(newName.trim())
                    newName = ""; showCreate = false
                }) { Text("Create", color = Brass) }
            },
            dismissButton = { TextButton(onClick = { showCreate = false }) { Text("Cancel") } },
            containerColor = ButlerSurface
        )
    }
}

/** Pinned entry for Liked Songs, styled like a playlist row but distinct enough to spot at a glance. */
@Composable
private fun LikedSongsRow(count: Int, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            Modifier
                .size(52.dp)
                .clip(RoundedCornerShape(4.dp))
                .background(Oxblood),
            contentAlignment = Alignment.Center
        ) {
            Icon(Icons.Filled.Favorite, contentDescription = null, tint = Color.White, modifier = Modifier.size(24.dp))
        }
        Spacer(Modifier.width(12.dp))
        Column {
            Text("Liked Songs", style = MaterialTheme.typography.titleMedium)
            Text("$count songs", style = MaterialTheme.typography.bodySmall, color = Stone)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SearchTab(vm: MainViewModel, onSongClick: (List<Song>, Song) -> Unit, onToggleLike: (Song) -> Unit) {
    var query by remember { mutableStateOf("") }
    val results by vm.searchResults.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize()) {
        TextField(
            value = query,
            onValueChange = { query = it },
            modifier = Modifier.fillMaxWidth().padding(16.dp).clip(RoundedCornerShape(24.dp)),
            placeholder = { Text("Search songs and artists") },
            singleLine = true,
            leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null, tint = Stone) },
            colors = TextFieldDefaults.colors(
                focusedContainerColor = SurfaceRaised,
                unfocusedContainerColor = SurfaceRaised,
                focusedIndicatorColor = androidx.compose.ui.graphics.Color.Transparent,
                unfocusedIndicatorColor = androidx.compose.ui.graphics.Color.Transparent,
                cursorColor = Brass
            ),
            keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(imeAction = ImeAction.Search),
            keyboardActions = KeyboardActions(onSearch = { vm.search(query) })
        )
        when (val state = results) {
            is LoadState.Loading -> LoadingState()
            is LoadState.Failed -> ErrorState(state.message)
            is LoadState.Loaded -> if (state.value.isEmpty()) {
                EmptyState(
                    if (query.isBlank()) "Search your library or find new songs" else "No results",
                    icon = Icons.Filled.Search
                )
            } else {
                LazyColumn {
                    items(state.value, key = { it.youtubeId }) { song ->
                        SongRow(
                            song = song,
                            onClick = { onSongClick(state.value, song) },
                            onToggleLike = { onToggleLike(song) }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun PlaylistRow(playlist: Playlist, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        SongArtwork(playlist.thumbnail, size = 52.dp)
        Spacer(Modifier.width(12.dp))
        Column {
            Text(playlist.name, style = MaterialTheme.typography.titleMedium)
            Text(
                "${playlist.songCount} songs" + if (playlist.shared) " · shared" else "",
                style = MaterialTheme.typography.bodySmall,
                color = Stone
            )
        }
    }
}
