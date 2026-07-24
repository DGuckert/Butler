package com.butler.music.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.butler.music.ButlerApp
import com.butler.music.network.ApiClient
import com.butler.music.network.Playlist
import com.butler.music.network.Song
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

sealed class LoadState<out T> {
    object Loading : LoadState<Nothing>()
    data class Loaded<T>(val value: T) : LoadState<T>()
    data class Failed(val message: String) : LoadState<Nothing>()
}

class MainViewModel(private val api: ApiClient) : ViewModel() {

    private val _library = MutableStateFlow<LoadState<List<Song>>>(LoadState.Loading)
    val library: StateFlow<LoadState<List<Song>>> = _library.asStateFlow()

    private val _liked = MutableStateFlow<LoadState<List<Song>>>(LoadState.Loading)
    val liked: StateFlow<LoadState<List<Song>>> = _liked.asStateFlow()

    private val _playlists = MutableStateFlow<LoadState<List<Playlist>>>(LoadState.Loading)
    val playlists: StateFlow<LoadState<List<Playlist>>> = _playlists.asStateFlow()

    private val _dailyMix = MutableStateFlow<LoadState<List<Song>>>(LoadState.Loading)
    val dailyMix: StateFlow<LoadState<List<Song>>> = _dailyMix.asStateFlow()

    private val _recentlyPlayed = MutableStateFlow<LoadState<List<Song>>>(LoadState.Loading)
    val recentlyPlayed: StateFlow<LoadState<List<Song>>> = _recentlyPlayed.asStateFlow()

    private val _recommendations = MutableStateFlow<LoadState<List<Song>>>(LoadState.Loading)
    val recommendations: StateFlow<LoadState<List<Song>>> = _recommendations.asStateFlow()

    private val _searchResults = MutableStateFlow<LoadState<List<Song>>>(LoadState.Loaded(emptyList()))
    val searchResults: StateFlow<LoadState<List<Song>>> = _searchResults.asStateFlow()

    private val likedIds = mutableSetOf<String>()

    init {
        refreshAll()
    }

    fun refreshAll() {
        loadLibrary()
        loadLiked()
        loadPlaylists()
        loadDailyMix()
        loadRecentlyPlayed()
        loadRecommendations()
    }

    fun loadLibrary() = viewModelScope.launch {
        _library.value = LoadState.Loading
        _library.value = runCatching { api.library() }
            .fold({ LoadState.Loaded(applyLiked(it)) }, { LoadState.Failed(it.message ?: "Failed to load library") })
    }

    fun loadLiked() = viewModelScope.launch {
        _liked.value = LoadState.Loading
        _liked.value = runCatching { api.liked() }
            .fold(
                {
                    likedIds.clear(); likedIds.addAll(it.map { s -> s.youtubeId })
                    LoadState.Loaded(it.map { s -> s.copy(liked = true) })
                },
                { LoadState.Failed(it.message ?: "Failed to load liked songs") }
            )
    }

    fun loadPlaylists() = viewModelScope.launch {
        _playlists.value = LoadState.Loading
        _playlists.value = runCatching { api.playlists() }
            .fold({ LoadState.Loaded(it) }, { LoadState.Failed(it.message ?: "Failed to load playlists") })
    }

    fun loadDailyMix() = viewModelScope.launch {
        _dailyMix.value = LoadState.Loading
        _dailyMix.value = runCatching { api.dailyMix() }
            .fold({ LoadState.Loaded(applyLiked(it)) }, { LoadState.Failed(it.message ?: "Daily Mix isn't available yet") })
    }

    fun regenerateDailyMix() = viewModelScope.launch {
        runCatching { api.regenerateDailyMix() }
        loadDailyMix()
    }

    fun loadRecentlyPlayed() = viewModelScope.launch {
        _recentlyPlayed.value = LoadState.Loading
        _recentlyPlayed.value = runCatching { api.history() }
            .fold({ LoadState.Loaded(applyLiked(it)) }, { LoadState.Failed(it.message ?: "Couldn't load recently played") })
    }

    fun loadRecommendations() = viewModelScope.launch {
        _recommendations.value = LoadState.Loading
        _recommendations.value = runCatching { api.recommendations() }
            .fold({ LoadState.Loaded(applyLiked(it)) }, { LoadState.Failed(it.message ?: "Couldn't load recommendations") })
    }

    fun search(query: String) = viewModelScope.launch {
        if (query.trim().length < 2) { _searchResults.value = LoadState.Loaded(emptyList()); return@launch }
        _searchResults.value = LoadState.Loading
        _searchResults.value = runCatching { api.search(query) }
            .fold({ LoadState.Loaded(applyLiked(it)) }, { LoadState.Failed(it.message ?: "Search failed") })
    }

    fun toggleLike(song: Song) = viewModelScope.launch {
        runCatching {
            if (song.liked) api.unlike(song.youtubeId) else api.like(song.youtubeId)
        }.onSuccess {
            if (song.liked) likedIds.remove(song.youtubeId) else likedIds.add(song.youtubeId)
            loadLiked()
            _library.value = mapLoaded(_library.value) { applyLiked(it) }
            _dailyMix.value = mapLoaded(_dailyMix.value) { applyLiked(it) }
            _searchResults.value = mapLoaded(_searchResults.value) { applyLiked(it) }
            _recentlyPlayed.value = mapLoaded(_recentlyPlayed.value) { applyLiked(it) }
            _recommendations.value = mapLoaded(_recommendations.value) { applyLiked(it) }
        }
    }

    fun createPlaylist(name: String) = viewModelScope.launch {
        runCatching { api.createPlaylist(name) }.onSuccess { loadPlaylists() }
    }

    private fun applyLiked(songs: List<Song>): List<Song> =
        songs.map { it.copy(liked = likedIds.contains(it.youtubeId)) }

    private fun mapLoaded(state: LoadState<List<Song>>, transform: (List<Song>) -> List<Song>): LoadState<List<Song>> =
        if (state is LoadState.Loaded) LoadState.Loaded(transform(state.value)) else state

    companion object {
        fun factory() = viewModelFactory {
            initializer {
                val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY] as ButlerApp
                MainViewModel(app.api)
            }
        }
    }
}
