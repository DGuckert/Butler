package com.butler.music

import android.Manifest
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
import com.butler.music.ui.theme.ButlerTheme

class MainActivity : ComponentActivity() {

    private lateinit var playerController: PlayerController

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val app = application as ButlerApp
        playerController = PlayerController(this, app.api, app.downloads)
        playerController.connect()

        setContent {
            ButlerTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    var loggedIn by remember { mutableStateOf(app.prefs.isLoggedIn) }

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

                    if (loggedIn) {
                        MainScreen(
                            player = playerController,
                            onLogout = {
                                app.prefs.clearSession()
                                loggedIn = false
                            }
                        )
                    } else {
                        LoginScreen(onLoggedIn = { loggedIn = true })
                    }
                }
            }
        }
    }

    override fun onDestroy() {
        playerController.release()
        super.onDestroy()
    }
}
