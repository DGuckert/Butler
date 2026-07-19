package com.butler.music.playback

import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import com.butler.music.ButlerApp

/**
 * Background playback service. Runs an ExoPlayer + MediaSession so audio
 * keeps playing with lock-screen / notification controls, the same way
 * Jellyfin's Finamp client or any standard music app does it.
 *
 * Streaming requests need the same bearer token the REST API uses, so we
 * attach it to every HTTP request made by the player's data source.
 */
class PlaybackService : MediaSessionService() {

    private var mediaSession: MediaSession? = null

    override fun onCreate() {
        super.onCreate()

        val app = application as ButlerApp
        val prefs = app.prefs

        val httpDataSourceFactory = DefaultHttpDataSource.Factory()
            .setUserAgent("Butler-Android")
            .setDefaultRequestProperties(emptyMap())
            .setAllowCrossProtocolRedirects(true)

        // Attach the current bearer token to every request, re-read at
        // connection time so login/logout is picked up without restarting
        // the service.
        val factory = androidx.media3.datasource.DataSource.Factory {
            httpDataSourceFactory.setDefaultRequestProperties(
                prefs.token?.let { mapOf("Authorization" to "Bearer $it") } ?: emptyMap()
            )
            httpDataSourceFactory.createDataSource()
        }

        val player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(factory))
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(C.USAGE_MEDIA)
                    .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                    .build(),
                /* handleAudioFocus = */ true
            )
            .setHandleAudioBecomingNoisy(true)
            .build()

        mediaSession = MediaSession.Builder(this, player).build()
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = mediaSession

    override fun onDestroy() {
        mediaSession?.run {
            player.release()
            release()
            mediaSession = null
        }
        super.onDestroy()
    }
}
