package com.butler.music.playback

import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import com.butler.music.network.ApiClient
import com.butler.music.network.Song

/**
 * Shared MediaItem construction so PlayerController (in-app playback) and
 * PlaybackService's Android Auto browse tree build identical items instead
 * of two copies that could quietly drift apart.
 */
fun Song.toMediaItem(api: ApiClient): MediaItem {
    val metadata = MediaMetadata.Builder()
        .setTitle(title)
        .setArtist(artist)
        .setArtworkUri(thumbnail?.let { android.net.Uri.parse(it) })
        .setIsBrowsable(false)
        .setIsPlayable(true)
        .build()
    return MediaItem.Builder()
        .setMediaId(youtubeId)
        .setUri(api.streamUrl(youtubeId))
        .setMediaMetadata(metadata)
        .build()
}

/** A folder node in the Android Auto / media browser tree (e.g. "Liked Songs", a playlist). */
fun browsableItem(id: String, title: String, subtitle: String? = null): MediaItem {
    val metadata = MediaMetadata.Builder()
        .setTitle(title)
        .setSubtitle(subtitle)
        .setIsBrowsable(true)
        .setIsPlayable(false)
        .build()
    return MediaItem.Builder()
        .setMediaId(id)
        .setMediaMetadata(metadata)
        .build()
}
