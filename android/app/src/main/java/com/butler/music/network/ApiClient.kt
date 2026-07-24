package com.butler.music.network

import com.butler.music.data.Prefs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

private val JSON = "application/json; charset=utf-8".toMediaType()

/**
 * Thin REST client for a Butler server. One instance is shared across the
 * app (see ButlerApp) and re-reads the server URL / token from Prefs on
 * every call, so switching servers or logging out takes effect immediately.
 */
class ApiClient(private val prefs: Prefs) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .addInterceptor(AuthInterceptor())
        .build()

    private inner class AuthInterceptor : Interceptor {
        override fun intercept(chain: Interceptor.Chain): Response {
            val builder = chain.request().newBuilder()
            prefs.token?.let { builder.addHeader("Authorization", "Bearer $it") }
            return chain.proceed(builder.build())
        }
    }

    val baseUrl: String get() = prefs.serverUrl

    fun authToken(): String? = prefs.token

    fun streamUrl(youtubeId: String): String = "$baseUrl/songs/stream/$youtubeId"

    // ── low-level helpers ──────────────────────────────────────────────

    private suspend fun get(path: String): JSONObject = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(baseUrl + path).get().build()
        execute(req)
    }

    private suspend fun post(path: String, body: JSONObject = JSONObject()): JSONObject =
        withContext(Dispatchers.IO) {
            val req = Request.Builder()
                .url(baseUrl + path)
                .post(body.toString().toRequestBody(JSON))
                .build()
            execute(req)
        }

    private suspend fun patch(path: String, body: JSONObject): JSONObject =
        withContext(Dispatchers.IO) {
            val req = Request.Builder()
                .url(baseUrl + path)
                .patch(body.toString().toRequestBody(JSON))
                .build()
            execute(req)
        }

    private suspend fun delete(path: String): JSONObject = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(baseUrl + path).delete().build()
        execute(req)
    }

    private fun execute(req: Request): JSONObject {
        client.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                val detail = runCatching { JSONObject(text).optString("detail") }.getOrNull()
                throw ApiException(detail ?: "Server error (${resp.code})", resp.code)
            }
            return if (text.isBlank()) JSONObject() else JSONObject(text)
        }
    }

    private fun songsFrom(obj: JSONObject, key: String): List<Song> {
        val arr: JSONArray = obj.optJSONArray(key) ?: return emptyList()
        return (0 until arr.length()).map { Song.fromJson(arr.getJSONObject(it)) }
    }

    // ── auth ────────────────────────────────────────────────────────────

    suspend fun login(username: String, password: String): CurrentUser {
        val body = JSONObject().put("username", username).put("password", password)
        val res = post("/auth/login", body)
        prefs.token = res.optString("token")
        prefs.username = res.optString("username")
        return CurrentUser(0, res.optString("username"))
    }

    suspend fun register(username: String, password: String, inviteCode: String): CurrentUser {
        val body = JSONObject()
            .put("username", username)
            .put("password", password)
            .put("invite_code", inviteCode)
        val res = post("/auth/register", body)
        prefs.token = res.optString("token")
        prefs.username = res.optString("username")
        return CurrentUser(0, res.optString("username"))
    }

    /** Checks that a server is reachable and looks like Butler before we try to log in. */
    suspend fun ping(serverUrl: String): Boolean = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder().url("${serverUrl.trimEnd('/')}/search?q=a").get().build()
            client.newCall(req).execute().use { it.code == 401 || it.code == 200 }
        }.getOrDefault(false)
    }

    // ── library / search / playback ────────────────────────────────────

    suspend fun search(query: String): List<Song> = songsFrom(get("/search?q=${enc(query)}"), "results")

    suspend fun library(sort: String = "date"): List<Song> = songsFrom(get("/library?sort=$sort"), "songs")

    suspend fun liked(): List<Song> = songsFrom(get("/liked"), "songs")

    suspend fun history(): List<Song> = songsFrom(get("/history"), "history")

    suspend fun recommendations(): List<Song> = songsFrom(get("/recommendations"), "songs")

    suspend fun discovery(): List<Song> = songsFrom(get("/discovery"), "songs")

    suspend fun dailyMix(): List<Song> = songsFrom(get("/daily-mix"), "songs")

    suspend fun regenerateDailyMix() { post("/daily-mix/regenerate") }

    suspend fun playSong(youtubeId: String): String {
        val res = post("/songs/play/$youtubeId")
        return res.optString("status")
    }

    suspend fun songStatus(youtubeId: String): String = get("/songs/status/$youtubeId").optString("status")

    suspend fun like(youtubeId: String) { post("/songs/$youtubeId/like") }

    suspend fun unlike(youtubeId: String) { delete("/songs/$youtubeId/like") }

    // ── playlists ───────────────────────────────────────────────────────

    suspend fun playlists(): List<Playlist> {
        val arr = get("/playlists").optJSONArray("playlists") ?: JSONArray()
        return (0 until arr.length()).map { Playlist.fromJson(arr.getJSONObject(it)) }
    }

    suspend fun playlist(id: Int): Pair<Playlist, List<Song>> {
        val res = get("/playlists/$id")
        val playlist = Playlist.fromJson(res.getJSONObject("playlist"))
        return playlist to songsFrom(res, "songs")
    }

    suspend fun createPlaylist(name: String, shared: Boolean = false): Playlist {
        val body = JSONObject().put("name", name).put("shared", shared)
        return Playlist.fromJson(post("/playlists", body))
    }

    suspend fun renamePlaylist(id: Int, name: String) {
        patch("/playlists/$id", JSONObject().put("name", name))
    }

    suspend fun deletePlaylist(id: Int) { delete("/playlists/$id") }

    suspend fun addToPlaylist(playlistId: Int, youtubeId: String) {
        post("/playlists/$playlistId/songs/$youtubeId")
    }

    suspend fun removeFromPlaylist(playlistId: Int, youtubeId: String) {
        delete("/playlists/$playlistId/songs/$youtubeId")
    }

    private fun enc(s: String): String = java.net.URLEncoder.encode(s, "UTF-8")
}
