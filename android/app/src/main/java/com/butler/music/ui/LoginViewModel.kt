package com.butler.music.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.lifecycle.viewmodel.initializer
import com.butler.music.ButlerApp
import com.butler.music.network.ApiClient
import com.butler.music.network.ApiException
import com.butler.music.data.Prefs
import kotlinx.coroutines.launch

class LoginViewModel(private val api: ApiClient, private val prefs: Prefs) : ViewModel() {

    var serverUrl by mutableStateOf(prefs.serverUrl)
    var username by mutableStateOf("")
    var password by mutableStateOf("")
    var inviteCode by mutableStateOf("")
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    fun login(onSuccess: () -> Unit) {
        if (!validateCommon()) return
        loading = true; error = null
        viewModelScope.launch {
            try {
                prefs.serverUrl = normalized(serverUrl)
                api.login(username.trim(), password)
                onSuccess()
            } catch (e: ApiException) {
                error = e.message
            } catch (e: Exception) {
                error = "Could not reach server. Check the address and try again."
            } finally {
                loading = false
            }
        }
    }

    fun register(onSuccess: () -> Unit) {
        if (!validateCommon()) return
        if (inviteCode.isBlank()) { error = "An invite code is required"; return }
        loading = true; error = null
        viewModelScope.launch {
            try {
                prefs.serverUrl = normalized(serverUrl)
                api.register(username.trim(), password, inviteCode.trim())
                onSuccess()
            } catch (e: ApiException) {
                error = e.message
            } catch (e: Exception) {
                error = "Could not reach server. Check the address and try again."
            } finally {
                loading = false
            }
        }
    }

    private fun validateCommon(): Boolean {
        if (serverUrl.isBlank()) { error = "Enter your Butler server address"; return false }
        if (username.isBlank() || password.isBlank()) { error = "Enter a username and password"; return false }
        return true
    }

    private fun normalized(url: String): String {
        val trimmed = url.trim().trimEnd('/')
        return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) trimmed else "http://$trimmed"
    }

    companion object {
        fun factory() = viewModelFactory {
            initializer {
                val app = this[ViewModelProvider.AndroidViewModelFactory.APPLICATION_KEY] as ButlerApp
                LoginViewModel(app.api, app.prefs)
            }
        }
    }
}
