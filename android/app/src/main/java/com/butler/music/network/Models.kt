package com.butler.music.network

import org.json.JSONObject

data class Song(
    val id: Int,
    val youtubeId: String,
    val title: String,
    val artist: String,
    val duration: Int,
    val thumbnail: String?,
    val downloaded: Boolean,
    val liked: Boolean = false
) {
    companion object {
        fun fromJson(o: JSONObject): Song = Song(
            id = o.optInt("id"),
            youtubeId = o.optString("youtube_id"),
            title = o.optString("title", "Unknown title"),
            artist = o.optString("artist", "Unknown artist"),
            duration = o.optInt("duration", 0),
            thumbnail = o.optString("thumbnail", "").ifBlank { null },
            downloaded = o.optInt("downloaded", 0) == 1 || o.optBoolean("downloaded", false)
        )
    }
}

data class Playlist(
    val id: Int,
    val name: String,
    val ownerName: String,
    val shared: Boolean,
    val songCount: Int,
    val thumbnail: String?,
    val canEdit: Boolean = true
) {
    companion object {
        fun fromJson(o: JSONObject): Playlist = Playlist(
            id = o.optInt("id"),
            name = o.optString("name", "Untitled"),
            ownerName = o.optString("owner_name", ""),
            shared = o.optInt("shared", 0) == 1 || o.optBoolean("shared", false),
            songCount = o.optInt("song_count", 0),
            thumbnail = o.optString("thumbnail", "").ifBlank { null },
            canEdit = o.optBoolean("can_edit", true)
        )
    }
}

data class CurrentUser(
    val id: Int,
    val username: String
)

class ApiException(message: String, val code: Int = 0) : Exception(message)
