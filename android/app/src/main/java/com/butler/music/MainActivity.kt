package com.butler.music

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import com.butler.music.playback.PlayerController
import com.butler.music.ui.LoginScreen
import com.butler.music.ui.MainScreen
import com.butler.music.ui.theme.ButlerTheme

class MainActivity : ComponentActivity() {

    private lateinit var playerController: PlayerController

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val app = application as ButlerApp
        playerController = PlayerController(this, app.api)
        playerController.connect()

        setContent {
            ButlerTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    var loggedIn by remember { mutableStateOf(app.prefs.isLoggedIn) }

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
