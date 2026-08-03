package com.butler.music.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.butler.music.ButlerApp
import com.butler.music.network.ApiException
import com.butler.music.ui.theme.Brass
import com.butler.music.ui.theme.Ink
import com.butler.music.ui.theme.Stone
import com.butler.music.ui.theme.SurfaceRaised
import kotlinx.coroutines.launch

/**
 * First screen the app shows (unless a server is already remembered from
 * last time) -- Jellyfin-style split between "which server" and "who are
 * you", rather than one combined form. Only has to confirm the address is
 * a real, reachable Butler server; the actual login/SSO choice happens on
 * LoginScreen once connected, since which SSO providers are even available
 * is itself a property of the server picked here.
 */
@Composable
fun ServerSelectScreen(onConnected: () -> Unit) {
    val app = LocalContext.current.applicationContext as ButlerApp
    val scope = rememberCoroutineScope()

    var serverUrl by remember { mutableStateOf(app.prefs.serverUrl) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun normalized(url: String): String {
        val trimmed = url.trim().trimEnd('/')
        return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) trimmed else "http://$trimmed"
    }

    fun connect() {
        if (serverUrl.isBlank()) { error = "Enter your Butler server address"; return }
        loading = true; error = null
        val target = normalized(serverUrl)
        scope.launch {
            try {
                // Reachability + "is this actually Butler" check in one --
                // /auth/oidc/status needs no auth and any Butler server
                // answers it, so a successful call here is enough proof.
                app.api.oidcProviders(target)
                app.prefs.serverUrl = target
                onConnected()
            } catch (e: ApiException) {
                error = "That doesn't look like a Butler server (${e.message})"
            } catch (e: Exception) {
                error = "Could not reach that server. Check the address and try again."
            } finally {
                loading = false
            }
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .background(Ink)
            .padding(28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Icon(
            Icons.Filled.MusicNote,
            contentDescription = null,
            modifier = Modifier.size(40.dp),
            tint = Brass
        )
        Spacer(Modifier.height(10.dp))
        Text("Butler", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(4.dp))
        Text(
            "Where's your library?",
            style = MaterialTheme.typography.bodyMedium,
            color = Stone
        )
        Spacer(Modifier.height(36.dp))

        TextField(
            value = serverUrl,
            onValueChange = { serverUrl = it },
            label = { Text("Server address") },
            placeholder = { Text("http://192.168.1.10:8080") },
            singleLine = true,
            colors = TextFieldDefaults.colors(
                focusedContainerColor = SurfaceRaised,
                unfocusedContainerColor = SurfaceRaised,
                focusedIndicatorColor = androidx.compose.ui.graphics.Color.Transparent,
                unfocusedIndicatorColor = androidx.compose.ui.graphics.Color.Transparent,
                cursorColor = Brass,
                focusedLabelColor = Brass
            ),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(Modifier.height(22.dp))

        if (error != null) {
            Text(
                error ?: "",
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(bottom = 14.dp)
            )
        }

        Button(
            onClick = { connect() },
            enabled = !loading,
            colors = ButtonDefaults.buttonColors(containerColor = Brass, contentColor = Ink),
            modifier = Modifier.fillMaxWidth().height(50.dp)
        ) {
            if (loading) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp), color = Ink, strokeWidth = 2.dp)
            } else {
                Text("Connect", style = MaterialTheme.typography.labelLarge)
            }
        }
    }
}
