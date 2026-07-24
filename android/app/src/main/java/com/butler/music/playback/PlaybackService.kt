package com.butler.music.playback

import android.content.Intent
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.LibraryResult
import androidx.media3.session.MediaLibraryService
import androidx.media3.session.MediaSession
import androidx.media3.session.SessionCommand
import androidx.media3.session.SessionResult
import com.butler.music.ButlerApp
import com.butler.music.network.ApiClient
import com.butler.music.network.Song
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.guava.future as guavaFuture

/**
 * Background playback service, and (via MediaLibraryService) the Android
 * Auto / Android Automotive entry point. The same session that drives the
 * in-app mini player and lock-screen controls also answers "what can I
 * browse/play" questions from a car head unit or Google Assistant --
 * there's only one source of truth for what's playable.
 *
 * The browse tree is intentionally the same short list Home links to on
 * the web: Liked Songs, Playlists, Daily Mix, Recently Played. Streaming
 * requests need the same bearer token the REST API uses, so it's attached
 * to every HTTP request the player's data source makes.
 */
@UnstableApi
class PlaybackService : MediaLibraryService() {

    private var mediaLibrarySession: MediaLibrarySession? = null
    private lateinit var api: ApiClient
    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    companion object {
        private const val ROOT_ID = "root"
        private const val LIKED_ID = "liked"
        private const val PLAYLISTS_ID = "playlists"
        private const val DAILY_MIX_ID = "daily_mix"
        private const val HISTORY_ID = "history"
        private const val PLAYLIST_PREFIX = "playlist:"
    }

    override fun onCreate() {
        super.onCreate()

        val app = application as ButlerApp
        val prefs = app.prefs
        api = app.api

        val httpDataSourceFactory = DefaultHttpDataSource.Factory()
            .setUserAgent("Butler-Android")
            .setAllowCrossProtocolRedirects(true)

        val dataSourceFactory = androidx.media3.datasource.DataSource.Factory {
            httpDataSourceFactory.setDefaultRequestProperties(
                prefs.token?.let { mapOf("Authorization" to "Bearer $it") } ?: emptyMap()
            )
            httpDataSourceFactory.createDataSource()
        }

        val player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(dataSourceFactory))
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(C.USAGE_MEDIA)
                    .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                    .build(),
                /* handleAudioFocus = */ true
            )
            .setHandleAudioBecomingNoisy(true)
            .build()

        mediaLibrarySession = MediaLibrarySession.Builder(this, player, LibraryCallback())
            .build()
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaLibrarySession? =
        mediaLibrarySession

    override fun onDestroy() {
        mediaLibrarySession?.run {
            player.release()
            release()
            mediaLibrarySession = null
        }
        super.onDestroy()
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Stop when the app is swiped away and nothing's playing, same as
        // most music apps -- don't linger as a silent background service.
        val player = mediaLibrarySession?.player
        if (player == null || !player.playWhenReady || player.mediaItemCount == 0) {
            stopSelf()
        }
        super.onTaskRemoved(rootIntent)
    }

    private inner class LibraryCallback : MediaLibrarySession.Callback {

        override fun onGetLibraryRoot(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            params: LibraryParams?
        ): ListenableFuture<LibraryResult<MediaItem>> =
            Futures.immediateFuture(LibraryResult.ofItem(browsableItem(ROOT_ID, "Butler"), params))

        override fun onGetChildren(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            parentId: String,
            page: Int,
            pageSize: Int,
            params: LibraryParams?
        ): ListenableFuture<LibraryResult<com.google.common.collect.ImmutableList<MediaItem>>> =
            serviceScope.guavaFuture {
                val children = when {
                    parentId == ROOT_ID -> listOf(
                        browsableItem(LIKED_ID, "Liked Songs"),
                        browsableItem(PLAYLISTS_ID, "Playlists"),
                        browsableItem(DAILY_MIX_ID, "Daily Mix"),
                        browsableItem(HISTORY_ID, "Recently Played"),
                    )
                    parentId == LIKED_ID ->
                        runCatching { api.liked() }.getOrDefault(emptyList()).map { it.toMediaItem(api) }
                    parentId == DAILY_MIX_ID ->
                        runCatching { api.dailyMix() }.getOrDefault(emptyList()).map { it.toMediaItem(api) }
                    parentId == HISTORY_ID ->
                        runCatching { api.history() }.getOrDefault(emptyList()).map { it.toMediaItem(api) }
                    parentId == PLAYLISTS_ID ->
                        runCatching { api.playlists() }.getOrDefault(emptyList()).map {
                            browsableItem(PLAYLIST_PREFIX + it.id, it.name, "${it.songCount} songs")
                        }
                    parentId.startsWith(PLAYLIST_PREFIX) -> {
                        val id = parentId.removePrefix(PLAYLIST_PREFIX).toIntOrNull()
                        if (id == null) emptyList()
                        else runCatching { api.playlist(id).second }.getOrDefault(emptyList()).map { it.toMediaItem(api) }
                    }
                    else -> emptyList()
                }
                LibraryResult.ofItemList(com.google.common.collect.ImmutableList.copyOf(children), params)
            }

        override fun onGetItem(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            mediaId: String
        ): ListenableFuture<LibraryResult<MediaItem>> = serviceScope.guavaFuture {
            // mediaId here is a youtube_id (see Song.toMediaItem); resolving it means
            // re-fetching enough context to build a playable item. Liked songs cover
            // the common case cheaply; fall back to search by id isn't supported
            // server-side, so an unresolvable id just fails the lookup.
            val song = runCatching { api.liked() }.getOrNull()?.firstOrNull { it.youtubeId == mediaId }
                ?: runCatching { api.history() }.getOrNull()?.firstOrNull { it.youtubeId == mediaId }
            if (song != null) LibraryResult.ofItem(song.toMediaItem(api), null)
            else LibraryResult.ofError(LibraryResult.RESULT_ERROR_BAD_VALUE)
        }

        override fun onGetSearchResult(
            session: MediaLibrarySession,
            browser: MediaSession.ControllerInfo,
            query: String,
            page: Int,
            pageSize: Int,
            params: LibraryParams?
        ): ListenableFuture<LibraryResult<com.google.common.collect.ImmutableList<MediaItem>>> =
            serviceScope.guavaFuture {
                val results = runCatching { api.search(query) }.getOrDefault(emptyList()).map { it.toMediaItem(api) }
                LibraryResult.ofItemList(com.google.common.collect.ImmutableList.copyOf(results), params)
            }

        override fun onAddMediaItems(
            mediaSession: MediaSession,
            controller: MediaSession.ControllerInfo,
            mediaItems: MutableList<MediaItem>
        ): ListenableFuture<MutableList<MediaItem>> {
            // Auto/Assistant hand us bare MediaItems (mediaId only, sometimes just a
            // search query via requestMetadata); re-resolve each into a fully playable
            // item with a real stream URI the same way the in-app queue does.
            return serviceScope.guavaFuture {
                mediaItems.map { item ->
                    val song = runCatching { api.liked() }.getOrNull()?.firstOrNull { it.youtubeId == item.mediaId }
                        ?: runCatching { api.history() }.getOrNull()?.firstOrNull { it.youtubeId == item.mediaId }
                    if (song != null) {
                        runCatching { api.playSong(song.youtubeId) }
                        song.toMediaItem(api)
                    } else item
                }.toMutableList()
            }
        }
    }
}
