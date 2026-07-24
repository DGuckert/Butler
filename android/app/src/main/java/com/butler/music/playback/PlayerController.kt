package com.butler.music.playback

import android.content.ComponentName
import android.content.Context
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.butler.music.network.ApiClient
import com.butler.music.network.Song
import com.google.common.util.concurrent.MoreExecutors
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class PlayerUiState(
    val queue: List<Song> = emptyList(),
    val currentIndex: Int = -1,
    val isPlaying: Boolean = false,
    val isBuffering: Boolean = false,
    val positionMs: Long = 0L,
    val durationMs: Long = 0L
) {
    val currentSong: Song? get() = queue.getOrNull(currentIndex)
}

/**
 * Owns the MediaController connection to PlaybackService and exposes a
 * simple StateFlow the whole UI layer can collect. There is one instance
 * per process, created lazily from MainActivity.
 */
class PlayerController(private val context: Context, private val api: ApiClient, private val downloads: com.butler.music.data.DownloadManager? = null) {

    private val _state = MutableStateFlow(PlayerUiState())
    val state: StateFlow<PlayerUiState> = _state.asStateFlow()

    private var controller: MediaController? = null
    private var queueSongs: List<Song> = emptyList()
    private val scope = CoroutineScope(kotlinx.coroutines.Dispatchers.Main.immediate + SupervisorJob())
    private var positionPoller: Job? = null

    fun connect(onReady: () -> Unit = {}) {
        if (controller != null) { onReady(); return }
        val token = SessionToken(context, ComponentName(context, PlaybackService::class.java))
        val future = MediaController.Builder(context, token).buildAsync()
        future.addListener({
            controller = future.get()
            controller?.addListener(playerListener)
            startPositionPolling()
            onReady()
        }, MoreExecutors.directExecutor())
    }

    private val playerListener = object : Player.Listener {
        override fun onIsPlayingChanged(isPlaying: Boolean) {
            _state.value = _state.value.copy(isPlaying = isPlaying)
        }

        override fun onPlaybackStateChanged(playbackState: Int) {
            _state.value = _state.value.copy(
                isBuffering = playbackState == Player.STATE_BUFFERING,
                durationMs = controller?.duration?.coerceAtLeast(0) ?: 0L
            )
        }

        override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
            val index = controller?.currentMediaItemIndex ?: -1
            _state.value = _state.value.copy(currentIndex = index)
        }
    }

    /**
     * Replace the queue with [songs] and start playback at [startIndex].
     * The stream endpoint only waits for a file to exist, it never starts a
     * download itself, so we call /songs/play first to make sure the server
     * actually starts fetching a song that isn't downloaded yet.
     */
    fun playQueue(songs: List<Song>, startIndex: Int) {
        val c = controller ?: return
        queueSongs = songs
        val items = songs.map { it.toMediaItem(api, downloads) }
        c.setMediaItems(items, startIndex, 0L)
        c.prepare()
        _state.value = _state.value.copy(queue = songs, currentIndex = startIndex)
        val startSong = songs.getOrNull(startIndex)
        scope.launch {
            if (startSong != null) {
                runCatching { api.playSong(startSong.youtubeId) }
            }
            controller?.play()
        }
    }

    fun playPause() {
        val c = controller ?: return
        if (c.isPlaying) c.pause() else c.play()
    }

    fun next() { controller?.seekToNextMediaItem() }
    fun previous() { controller?.seekToPreviousMediaItem() }
    fun seekTo(positionMs: Long) { controller?.seekTo(positionMs) }

    fun currentPositionMs(): Long = controller?.currentPosition ?: 0L

    /** Keeps state.positionMs live so the mini player progress line moves without every screen having to poll separately. */
    private fun startPositionPolling() {
        positionPoller?.cancel()
        positionPoller = scope.launch {
            while (true) {
                _state.value = _state.value.copy(positionMs = controller?.currentPosition?.coerceAtLeast(0) ?: 0L)
                delay(500)
            }
        }
    }

    fun release() {
        positionPoller?.cancel()
        controller?.release()
        controller = null
    }
}
