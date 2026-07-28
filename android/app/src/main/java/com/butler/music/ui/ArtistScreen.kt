package com.butler.music.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import com.butler.music.network.Song
import com.butler.music.ui.theme.Brass
import com.butler.music.ui.theme.Ink
import com.butler.music.ui.theme.Stone
import com.butler.music.ui.theme.SurfaceRaised

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ArtistScreen(
    artistName: String,
    onBack: () -> Unit,
    onSongClick: (List<Song>, Song) -> Unit,
    onToggleLike: (Song) -> Unit
) {
    val app = androidx.compose.ui.platform.LocalContext.current.applicationContext as com.butler.music.ButlerApp
    val vm: ArtistViewModel = androidx.lifecycle.viewmodel.compose.viewModel(factory = ArtistViewModel.Factory(app.api, app.downloads, artistName))
    val state by vm.state.collectAsStateWithLifecycle()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(artistName, maxLines = 1) },
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
            when (val s = state) {
                is LoadState.Loading -> LoadingState()
                is LoadState.Failed -> ErrorState(s.message, onRetry = vm::load)
                is LoadState.Loaded -> {
                    val page = s.value
                    LazyColumn {
                        item { ArtistHeader(page.name, page.image, page.bio, page.songs.size) }
                        if (page.songs.isEmpty()) {
                            item { EmptyState("No tracks found for this artist yet.", icon = Icons.Filled.MusicNote) }
                        } else {
                            items(page.songs, key = { it.youtubeId }) { song ->
                                SongRow(
                                    song = song,
                                    onClick = { onSongClick(page.songs, song) },
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
}

@Composable
private fun ArtistHeader(name: String, image: String?, bio: String?, songCount: Int) {
    Column(Modifier.padding(20.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier
                    .size(96.dp)
                    .clip(CircleShape)
                    .background(SurfaceRaised),
                contentAlignment = Alignment.Center
            ) {
                if (image != null) {
                    AsyncImage(
                        model = image,
                        contentDescription = null,
                        modifier = Modifier.size(96.dp).clip(CircleShape)
                    )
                } else {
                    Icon(Icons.Filled.MusicNote, contentDescription = null, tint = Brass.copy(alpha = 0.75f), modifier = Modifier.size(40.dp))
                }
            }
            Spacer(Modifier.width(16.dp))
            Column {
                Text("ARTIST", style = MaterialTheme.typography.labelSmall, color = Brass)
                Text(name, style = MaterialTheme.typography.headlineSmall)
                Text("$songCount song${if (songCount != 1) "s" else ""}", style = MaterialTheme.typography.bodySmall, color = Stone)
            }
        }
        if (!bio.isNullOrBlank()) {
            Spacer(Modifier.height(16.dp))
            Text(bio, style = MaterialTheme.typography.bodyMedium, color = Stone)
        }
    }
}
