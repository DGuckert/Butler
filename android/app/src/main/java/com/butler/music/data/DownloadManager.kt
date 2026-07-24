package com.butler.music.data

import android.content.Context
import com.butler.music.network.ApiClient
import com.butler.music.network.Song
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

enum class DownloadState { NONE, DOWNLOADING, DOWNLOADED, FAILED }

/**
 * Offline download support: fetches a song's audio to app-private storage
 * and keeps a small local index of what's been saved, so downloaded songs
 * -- title, artist, artwork, and the ability to actually play them -- work
 * with no server connection at all, not just "already streamed once so the
 * OS media cache happens to still have it".
 *
 * The index is a flat JSON file rather than a database; the app has no
 * other local storage need that would justify pulling in Room for this.
 */
class DownloadManager(private val context: Context) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    private val downloadDir: File by lazy {
        File(context.filesDir, "downloads").apply { mkdirs() }
    }
    private val indexFile: File by lazy { File(context.filesDir, "downloads_index.json") }

    private val _downloaded = MutableStateFlow<List<Song>>(loadIndex())
    val downloaded: StateFlow<List<Song>> = _downloaded.asStateFlow()

    private val _states = MutableStateFlow<Map<String, DownloadState>>(
        loadIndex().associate { it.youtubeId to DownloadState.DOWNLOADED }
    )
    val states: StateFlow<Map<String, DownloadState>> = _states.asStateFlow()

    fun stateFor(youtubeId: String): DownloadState = _states.value[youtubeId] ?: DownloadState.NONE

    fun isDownloaded(youtubeId: String): Boolean = stateFor(youtubeId) == DownloadState.DOWNLOADED

    /** The local file for a downloaded song, or null if it isn't downloaded (or was deleted out from under the index). */
    fun localFile(youtubeId: String): File? {
        val f = File(downloadDir, "$youtubeId.mp3")
        return if (f.exists()) f else null
    }

    suspend fun download(song: Song, api: ApiClient): Boolean = withContext(Dispatchers.IO) {
        if (isDownloaded(song.youtubeId)) return@withContext true
        _states.update { it + (song.youtubeId to DownloadState.DOWNLOADING) }

        val dest = File(downloadDir, "${song.youtubeId}.mp3")
        val tmp = File(downloadDir, "${song.youtubeId}.mp3.part")
        val success = runCatching {
            // Make sure the server has actually finished fetching this song
            // before we try to pull it, same as the in-app streamer does.
            runCatching { api.playSong(song.youtubeId) }
            var status = "downloading"
            var attempts = 0
            while (status != "ready" && attempts < 120) {
                status = runCatching { api.songStatus(song.youtubeId) }.getOrDefault("downloading")
                if (status == "ready") break
                kotlinx.coroutines.delay(1000)
                attempts++
            }

            val req = Request.Builder()
                .url(api.streamUrl(song.youtubeId))
                .apply { api.authToken()?.let { addHeader("Authorization", "Bearer $it") } }
                .build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) error("Download failed: ${resp.code}")
                resp.body?.byteStream()?.use { input ->
                    tmp.outputStream().use { output -> input.copyTo(output) }
                } ?: error("Empty response body")
            }
            tmp.renameTo(dest)
        }.isSuccess

        if (success && dest.exists()) {
            _states.update { it + (song.youtubeId to DownloadState.DOWNLOADED) }
            _downloaded.update { list -> if (list.any { it.youtubeId == song.youtubeId }) list else list + song }
            saveIndex()
            true
        } else {
            tmp.delete()
            _states.update { it + (song.youtubeId to DownloadState.FAILED) }
            false
        }
    }

    suspend fun delete(youtubeId: String) = withContext(Dispatchers.IO) {
        File(downloadDir, "$youtubeId.mp3").delete()
        _states.update { it - youtubeId }
        _downloaded.update { list -> list.filterNot { it.youtubeId == youtubeId } }
        saveIndex()
    }

    private fun loadIndex(): List<Song> = runCatching {
        if (!indexFile.exists()) return@runCatching emptyList()
        val arr = JSONArray(indexFile.readText())
        (0 until arr.length()).map { Song.fromJson(arr.getJSONObject(it)) }
            .filter { File(File(context.filesDir, "downloads"), "${it.youtubeId}.mp3").exists() }
    }.getOrDefault(emptyList())

    private fun saveIndex() {
        runCatching {
            val arr = JSONArray()
            _downloaded.value.forEach { song ->
                arr.put(
                    JSONObject()
                        .put("id", song.id)
                        .put("youtube_id", song.youtubeId)
                        .put("title", song.title)
                        .put("artist", song.artist)
                        .put("duration", song.duration)
                        .put("thumbnail", song.thumbnail)
                        .put("downloaded", 1)
                )
            }
            indexFile.writeText(arr.toString())
        }
    }
}
