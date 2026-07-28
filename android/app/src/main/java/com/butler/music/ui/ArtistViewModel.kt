package com.butler.music.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.butler.music.data.DownloadManager
import com.butler.music.data.DownloadState
import com.butler.music.network.ApiClient
import com.butler.music.network.ArtistPage
import com.butler.music.network.Song
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class ArtistViewModel(
    private val api: ApiClient,
    private val downloads: DownloadManager,
    private val artistName: String
) : ViewModel() {

    private val _state = MutableStateFlow<LoadState<ArtistPage>>(LoadState.Loading)
    val state: StateFlow<LoadState<ArtistPage>> = _state.asStateFlow()

    init { load() }

    fun load() = viewModelScope.launch {
        _state.value = LoadState.Loading
        runCatching { api.artist(artistName) }
            .onSuccess { _state.value = LoadState.Loaded(it) }
            .onFailure { _state.value = LoadState.Failed(it.message ?: "Couldn't load this artist.") }
    }

    fun downloadStateFor(song: Song): DownloadState = downloads.stateFor(song.youtubeId)

    fun toggleDownload(song: Song) = viewModelScope.launch {
        if (downloads.isDownloaded(song.youtubeId)) downloads.delete(song.youtubeId)
        else downloads.download(song, api)
    }

    class Factory(private val api: ApiClient, private val downloads: DownloadManager, private val artistName: String) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            return ArtistViewModel(api, downloads, artistName) as T
        }
    }
}
