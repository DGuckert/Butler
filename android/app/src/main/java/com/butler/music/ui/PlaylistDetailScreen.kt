package com.butler.music.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.butler.music.ButlerApp
import com.butler.music.network.Song
import com.butler.music.ui.theme.Ink
import com.butler.music.ui.theme.Stone

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlaylistDetailScreen(
    playlistId: Int,
    onBack: () -> Unit,
    onSongClick: (List<Song>, Song) -> Unit,
    onToggleLike: (Song) -> Unit,
    onArtistClick: (String) -> Unit = {}
) {
    val app = LocalContext.current.applicationContext as ButlerApp
    val vm: PlaylistDetailViewModel = viewModel(
        factory = PlaylistDetailViewModel.Factory(app.api, app.downloads, playlistId)
    )
    val state by vm.state.collectAsStateWithLifecycle()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(state?.playlist?.name ?: "Playlist", style = MaterialTheme.typography.titleLarge) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = Stone)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Ink)
            )
        }
    ) { padding ->
        val current = state
        Box(Modifier.padding(padding)) {
            when {
                current == null -> LoadingState()
                current.songs.isEmpty() -> EmptyState("This playlist is empty.")
                else -> LazyColumn {
                    items(current.songs, key = { it.youtubeId }) { song ->
                        SongRow(
                            song = song,
                            onClick = { onSongClick(current.songs, song) },
                            onToggleLike = { onToggleLike(song) },
                            onArtistClick = { onArtistClick(song.artist) },
                            downloadState = vm.downloadStateFor(song),
                            onToggleDownload = { vm.toggleDownload(song) },
                            trailing = {
                                if (current.playlist?.canEdit == true) {
                                    IconButton(onClick = { vm.removeSong(song) }) {
                                        Icon(Icons.Filled.Delete, contentDescription = "Remove", tint = Stone)
                                    }
                                }
                            }
                        )
                    }
                }
            }
        }
    }
}
