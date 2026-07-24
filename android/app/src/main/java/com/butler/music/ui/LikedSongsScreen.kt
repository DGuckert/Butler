package com.butler.music.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.butler.music.network.Song
import com.butler.music.ui.theme.Ink
import com.butler.music.ui.theme.Stone

/** Full Liked Songs list, opened from its pinned row in Your Library. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LikedSongsScreen(
    vm: MainViewModel,
    onBack: () -> Unit,
    onSongClick: (List<Song>, Song) -> Unit,
    onToggleLike: (Song) -> Unit
) {
    val liked by vm.liked.collectAsStateWithLifecycle()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Liked Songs", style = MaterialTheme.typography.titleLarge) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = Stone)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Ink)
            )
        }
    ) { padding ->
        Box(Modifier.padding(padding)) {
            when (val state = liked) {
                is LoadState.Loading -> LoadingState()
                is LoadState.Failed -> ErrorState(state.message, onRetry = vm::loadLiked)
                is LoadState.Loaded -> if (state.value.isEmpty()) {
                    EmptyState("Songs you like will show up here.", icon = Icons.Filled.FavoriteBorder)
                } else {
                    LazyColumn {
                        items(state.value, key = { it.youtubeId }) { song ->
                            SongRow(
                                song = song,
                                onClick = { onSongClick(state.value, song) },
                                onToggleLike = { onToggleLike(song) },
                                downloadState = vm.downloadStateFor(song),
                                onToggleDownload = { vm.toggleDownload(song) }
                            )
                        }
                    }
                }
            }
        }
    }
}
