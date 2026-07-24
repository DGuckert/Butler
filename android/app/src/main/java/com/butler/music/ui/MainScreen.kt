package com.butler.music.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.clickable
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.compose.currentBackStackEntryAsState
import com.butler.music.network.Song
import com.butler.music.playback.PlayerController
import com.butler.music.ui.theme.Brass
import com.butler.music.ui.theme.Ink
import com.butler.music.ui.theme.Stone
import com.butler.music.ui.theme.Surface

private sealed class Tab(val route: String, val label: String, val icon: androidx.compose.ui.graphics.vector.ImageVector) {
    object Home : Tab("home", "Home", Icons.Filled.Home)
    object Search : Tab("search", "Search", Icons.Filled.Search)
    object Library : Tab("library", "Your Library", Icons.Filled.LibraryMusic)
}

private val tabs = listOf(Tab.Home, Tab.Search, Tab.Library)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(player: PlayerController, onLogout: () -> Unit) {
    val vm: MainViewModel = viewModel(factory = MainViewModel.factory())
    val navController = rememberNavController()
    var showNowPlaying by remember { mutableStateOf(false) }
    val playerState by player.state.collectAsStateWithLifecycle()

    fun playFrom(songs: List<Song>, song: Song) {
        val index = songs.indexOfFirst { it.youtubeId == song.youtubeId }.coerceAtLeast(0)
        player.playQueue(songs, index)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "Butler",
                        style = MaterialTheme.typography.titleLarge,
                        color = Brass
                    )
                },
                actions = {
                    IconButton(onClick = onLogout) {
                        Icon(Icons.AutoMirrored.Filled.Logout, contentDescription = "Log out", tint = Stone)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Ink)
            )
        },
        bottomBar = {
            Column {
                AnimatedVisibility(visible = playerState.currentSong != null) {
                    MiniPlayerBar(playerState, onClick = { showNowPlaying = true }, onPlayPause = { player.playPause() })
                }
                NavigationBar {
                    val backStack by navController.currentBackStackEntryAsState()
                    val current = backStack?.destination?.route
                    tabs.forEach { tab ->
                        NavigationBarItem(
                            selected = current == tab.route,
                            onClick = {
                                navController.navigate(tab.route) {
                                    popUpTo(navController.graph.startDestinationId) { saveState = true }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            icon = { Icon(tab.icon, contentDescription = tab.label) },
                            label = { Text(tab.label) }
                        )
                    }
                }
            }
        }
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = Tab.Home.route,
            modifier = Modifier.padding(padding)
        ) {
            composable(Tab.Home.route) {
                HomeTab(vm, onSongClick = { songs, song -> playFrom(songs, song) }, onToggleLike = vm::toggleLike)
            }
            composable(Tab.Search.route) {
                SearchTab(vm, onSongClick = { songs, song -> playFrom(songs, song) }, onToggleLike = vm::toggleLike)
            }
            composable(Tab.Library.route) {
                LibraryTab(
                    vm,
                    navController,
                    onSongClick = { songs, song -> playFrom(songs, song) },
                    onToggleLike = vm::toggleLike
                )
            }
            composable("liked") {
                LikedSongsScreen(
                    vm,
                    onBack = { navController.popBackStack() },
                    onSongClick = { songs, song -> playFrom(songs, song) },
                    onToggleLike = vm::toggleLike
                )
            }
            composable("downloads") {
                DownloadsScreen(
                    vm,
                    onBack = { navController.popBackStack() },
                    onSongClick = { songs, song -> playFrom(songs, song) },
                    onToggleLike = vm::toggleLike
                )
            }
            composable(
                "playlist/{id}",
                arguments = listOf(androidx.navigation.navArgument("id") { type = androidx.navigation.NavType.IntType })
            ) { backStackEntry ->
                val id = backStackEntry.arguments?.getInt("id") ?: return@composable
                PlaylistDetailScreen(
                    playlistId = id,
                    onBack = { navController.popBackStack() },
                    onSongClick = { songs, song -> playFrom(songs, song) },
                    onToggleLike = vm::toggleLike
                )
            }
        }
    }

    if (showNowPlaying) {
        NowPlayingSheet(player = player, onToggleLike = vm::toggleLike, onDismiss = { showNowPlaying = false })
    }
}

@Composable
private fun MiniPlayerBar(state: com.butler.music.playback.PlayerUiState, onClick: () -> Unit, onPlayPause: () -> Unit) {
    val song = state.currentSong ?: return
    val progress = if (state.durationMs > 0) {
        (state.positionMs.toFloat() / state.durationMs.toFloat()).coerceIn(0f, 1f)
    } else 0f

    Surface(color = Surface) {
        Column {
            LinearProgressIndicator(
                progress = { progress },
                modifier = Modifier.fillMaxWidth().height(2.dp),
                color = Brass,
                trackColor = Ink
            )
            Row(
                Modifier
                    .fillMaxWidth()
                    .clickableNoRipple(onClick)
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                SongArtwork(song.thumbnail, size = 40.dp)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(song.title, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.titleMedium)
                    Text(
                        song.artist,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        style = MaterialTheme.typography.bodySmall,
                        color = Stone
                    )
                }
                IconButton(onClick = onPlayPause) {
                    Icon(
                        if (state.isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                        contentDescription = "Play or pause",
                        tint = Brass
                    )
                }
            }
        }
    }
}

@Composable
private fun Modifier.clickableNoRipple(onClick: () -> Unit): Modifier =
    this.clickable(
        indication = null,
        interactionSource = remember { androidx.compose.foundation.interaction.MutableInteractionSource() },
        onClick = onClick
    )
