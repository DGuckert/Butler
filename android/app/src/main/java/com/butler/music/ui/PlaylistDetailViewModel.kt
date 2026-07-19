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
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class PlaylistDetailState(val playlist: Playlist?, val songs: List<Song>)

class PlaylistDetailViewModel(private val api: ApiClient, private val playlistId: Int) : ViewModel() {

    private val _state = MutableStateFlow<PlaylistDetailState?>(null)
    val state: StateFlow<PlaylistDetailState?> = _state.asStateFlow()

    init { load() }

    private fun load() = viewModelScope.launch {
        runCatching { api.playlist(playlistId) }.onSuccess { (playlist, songs) ->
            _state.value = PlaylistDetailState(playlist, songs)
        }
    }

    fun removeSong(song: Song) = viewModelScope.launch {
        runCatching { api.removeFromPlaylist(playlistId, song.youtubeId) }.onSuccess { load() }
    }

    companion object {
        fun factory(playlistId: Int) = viewModelFactory {
            initializer {
                val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY] as ButlerApp
                PlaylistDetailViewModel(app.api, playlistId)
            }
        }
    }
}
