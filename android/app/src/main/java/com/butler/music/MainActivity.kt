package com.butler.music

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import com.butler.music.playback.PlayerController
import com.butler.music.ui.LoginScreen
import com.butler.music.ui.MainScreen
import com.butler.music.ui.ServerSelectScreen
import com.butler.music.ui.theme.ButlerTheme
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    private lateinit var playerController: PlayerController

    // Set from onNewIntent when the SSO Custom Tab redirects back into the
    // app via the com.butler.music://oidc-callback deep link (see
    // AndroidManifest.xml's intent-filter on this activity). Compose
    // content below observes this and reacts with a LaunchedEffect --
    // onNewIntent itself isn't composable, so this is the hand-off point.
    private var pendingOidcIntent by mutableStateOf<Intent?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val app = application as ButlerApp
        playerController = PlayerController(this, app.api, app.downloads)
        playerController.connect()

        if (isOidcCallback(intent)) pendingOidcIntent = intent

        setContent {
            ButlerTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    var connected by remember { mutableStateOf(app.prefs.serverUrl.isNotBlank()) }
                    var loggedIn by remember { mutableStateOf(app.prefs.isLoggedIn) }
                    var oidcError by remember { mutableStateOf<String?>(null) }
                    val scope = rememberCoroutineScope()

                    // Media3's foreground playback service requires POST_NOTIFICATIONS
                    // to be granted at runtime on Android 13+ before it can post its
                    // notification. Without this, starting the session's foreground
                    // service throws a SecurityException that crashes the whole app —
                    // which is what was happening right after login, once the media
                    // session activated.
                    val context = LocalContext.current
                    val notificationPermissionLauncher = rememberLauncherForActivityResult(
                        ActivityResultContracts.RequestPermission()
                    ) { /* no-op: playback still works without the notification, just no lock-screen controls */ }

                    LaunchedEffect(Unit) {
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                            val granted = ContextCompat.checkSelfPermission(
                                context, Manifest.permission.POST_NOTIFICATIONS
                            ) == PackageManager.PERMISSION_GRANTED
                            if (!granted) {
                                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                            }
                        }
                    }

                    // Handles the SSO round trip landing back in the app: pull the
                    // token (or error) out of the deep link, save it the same way a
                    // normal password login would, fetch who actually just logged
                    // in (SSO never goes through api.login(), so the app doesn't
                    // know the username until now), then drop into the logged-in
                    // state. Clears pendingOidcIntent once handled so a
                    // configuration change doesn't replay it.
                    LaunchedEffect(pendingOidcIntent) {
                        val uri = pendingOidcIntent?.data ?: return@LaunchedEffect
                        val token = uri.getQueryParameter("token")
                        val error = uri.getQueryParameter("error")
                        if (token != null) {
                            app.prefs.token = token
                            scope.launch {
                                try {
                                    app.api.me()
                                } catch (e: Exception) {
                                    // Token is still valid even if this enrichment call
                                    // fails -- username just won't be pre-filled anywhere.
                                }
                                loggedIn = true
                            }
                        } else if (error != null) {
                            oidcError = error
                        }
                        pendingOidcIntent = null
                    }

                    when {
                        !connected -> ServerSelectScreen(onConnected = { connected = true })
                        !loggedIn -> LoginScreen(
                            onLoggedIn = { loggedIn = true; oidcError = null },
                            onChangeServer = {
                                app.prefs.clearSession()
                                app.prefs.serverUrl = ""
                                connected = false
                            },
                            oidcError = oidcError
                        )
                        else -> MainScreen(
                            player = playerController,
                            onLogout = {
                                app.prefs.clearSession()
                                loggedIn = false
                            }
                        )
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (isOidcCallback(intent)) pendingOidcIntent = intent
    }

    private fun isOidcCallback(intent: Intent?): Boolean =
        intent?.action == Intent.ACTION_VIEW && intent.data?.scheme == "com.butler.music"

    override fun onDestroy() {
        playerController.release()
        super.onDestroy()
    }
}
