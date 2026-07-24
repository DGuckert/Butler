package com.butler.music.playback

import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import com.butler.music.data.DownloadManager
import com.butler.music.network.ApiClient
import com.butler.music.network.Song

/**
 * Shared MediaItem construction so PlayerController (in-app playback) and
 * PlaybackService's Android Auto browse tree build identical items instead
 * of two copies that could quietly drift apart.
 *
 * When a song has been downloaded, the local file is used as the playback
 * URI instead of the network stream -- this is the one place that decision
 * is made, so offline playback and Auto-over-downloaded-songs both fall out
 * of it automatically rather than needing separate handling.
 */
fun Song.toMediaItem(api: ApiClient, downloads: DownloadManager? = null): MediaItem {
    val localFile = downloads?.localFile(youtubeId)
    val metadata = MediaMetadata.Builder()
        .setTitle(title)
        .setArtist(artist)
        .setArtworkUri(thumbnail?.let { android.net.Uri.parse(it) })
        .setIsBrowsable(false)
        .setIsPlayable(true)
        .build()
    val uri = localFile?.let { android.net.Uri.fromFile(it) } ?: android.net.Uri.parse(api.streamUrl(youtubeId))
    return MediaItem.Builder()
        .setMediaId(youtubeId)
        .setUri(uri)
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
