package com.butler.music.ui

import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.butler.music.network.ApiClient
import com.butler.music.network.ApiException
import com.butler.music.network.OidcProvider
import com.butler.music.data.Prefs
import kotlinx.coroutines.launch

class LoginViewModel(private val api: ApiClient, private val prefs: Prefs) : ViewModel() {

    // Server address is chosen on ServerSelectScreen before this screen is
    // ever shown -- kept here read-only so the UI can display which server
    // you're connecting to and offer a way back.
    val serverUrl: String get() = prefs.serverUrl

    var username by mutableStateOf("")
    var password by mutableStateOf("")
    var inviteCode by mutableStateOf("")
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    var ssoProviders by mutableStateOf<List<OidcProvider>>(emptyList())

    fun loadSsoProviders() {
        viewModelScope.launch {
            ssoProviders = try {
                api.oidcProviders()
            } catch (e: Exception) {
                emptyList()
            }
        }
    }

    fun login(onSuccess: () -> Unit) {
        if (!validateCommon()) return
        loading = true; error = null
        viewModelScope.launch {
            try {
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

    /** Builds the URL to open in a Custom Tab for a given SSO provider.
     * client=android tells the server to hand the token back via the
     * app's deep link instead of a web URL fragment (see oidc.py /
     * main.py on the server) -- everything else about the flow is
     * identical to the web login button. */
    fun ssoLoginUrl(providerKey: String): String {
        val builder = Uri.parse("$serverUrl/auth/oidc/login").buildUpon()
            .appendQueryParameter("provider", providerKey)
            .appendQueryParameter("client", "android")
        if (inviteCode.isNotBlank()) {
            builder.appendQueryParameter("invite", inviteCode.trim())
        }
        return builder.build().toString()
    }

    private fun validateCommon(): Boolean {
        if (username.isBlank() || password.isBlank()) { error = "Enter a username and password"; return false }
        return true
    }

    class Factory(private val api: ApiClient, private val prefs: Prefs) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            return LoginViewModel(api, prefs) as T
        }
    }
}
