package com.butler.music.ui

import androidx.browser.customtabs.CustomTabsIntent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.lifecycle.viewmodel.compose.viewModel
import com.butler.music.ButlerApp
import com.butler.music.ui.theme.Brass
import com.butler.music.ui.theme.Ink
import com.butler.music.ui.theme.Stone
import com.butler.music.ui.theme.SurfaceRaised

@Composable
fun LoginScreen(onLoggedIn: () -> Unit, onChangeServer: () -> Unit, oidcError: String? = null) {
    val app = LocalContext.current.applicationContext as ButlerApp
    val context = LocalContext.current
    val vm: LoginViewModel = viewModel(factory = LoginViewModel.Factory(app.api, app.prefs))
    var mode by remember { mutableStateOf(LoginMode.LOGIN) }
    // Matches the web login page's behavior: the invite field stays
    // hidden until either Register mode is picked, or an SSO attempt
    // comes back needing one -- most people never need to see it at all.
    var showInviteField by remember { mutableStateOf(false) }
    LaunchedEffect(oidcError) { if (oidcError != null) showInviteField = true }

    LaunchedEffect(Unit) { vm.loadSsoProviders() }

    val fieldColors = TextFieldDefaults.colors(
        focusedContainerColor = SurfaceRaised,
        unfocusedContainerColor = SurfaceRaised,
        focusedIndicatorColor = androidx.compose.ui.graphics.Color.Transparent,
        unfocusedIndicatorColor = androidx.compose.ui.graphics.Color.Transparent,
        cursorColor = Brass,
        focusedLabelColor = Brass
    )

    Column(
        Modifier
            .fillMaxSize()
            .background(Ink)
            .verticalScroll(rememberScrollState())
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
            vm.serverUrl,
            style = MaterialTheme.typography.bodySmall,
            color = Stone
        )
        Text(
            "Not your server?",
            style = MaterialTheme.typography.bodySmall,
            color = Brass,
            modifier = Modifier.clickableNoIndication(onChangeServer)
        )
        Spacer(Modifier.height(28.dp))

        SegmentedModeSwitch(mode) { mode = it }
        Spacer(Modifier.height(14.dp))

        TextField(
            value = vm.username,
            onValueChange = { vm.username = it },
            label = { Text("Username") },
            singleLine = true,
            colors = fieldColors,
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(Modifier.height(14.dp))
        TextField(
            value = vm.password,
            onValueChange = { vm.password = it },
            label = { Text("Password") },
            singleLine = true,
            colors = fieldColors,
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth()
        )

        if (mode == LoginMode.REGISTER || showInviteField) {
            Spacer(Modifier.height(14.dp))
            TextField(
                value = vm.inviteCode,
                onValueChange = { vm.inviteCode = it },
                label = { Text(if (mode == LoginMode.REGISTER) "Invite code" else "Invite code (for SSO sign-up)") },
                singleLine = true,
                colors = fieldColors,
                modifier = Modifier.fillMaxWidth()
            )
        }

        Spacer(Modifier.height(22.dp))

        if (vm.error != null) {
            Text(
                vm.error ?: "",
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(bottom = 14.dp)
            )
        }
        if (oidcError != null) {
            Text(
                oidcError,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(bottom = 14.dp)
            )
        }

        Button(
            onClick = {
                if (mode == LoginMode.LOGIN) vm.login(onLoggedIn) else vm.register(onLoggedIn)
            },
            enabled = !vm.loading,
            colors = ButtonDefaults.buttonColors(containerColor = Brass, contentColor = Ink),
            modifier = Modifier.fillMaxWidth().height(50.dp)
        ) {
            if (vm.loading) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp), color = Ink, strokeWidth = 2.dp)
            } else {
                Text(if (mode == LoginMode.LOGIN) "Log in" else "Create account", style = MaterialTheme.typography.labelLarge)
            }
        }

        // SSO buttons -- one per provider this server has enabled, same
        // idea as the web login page. Opens in a Custom Tab rather than
        // an in-app WebView so the person gets their browser's real
        // session (saved Google/Authelia logins, password manager, etc)
        // instead of having to type credentials into a view Butler
        // controls. The provider's flow finishes by redirecting to
        // com.butler.music://oidc-callback, which MainActivity picks up.
        if (vm.ssoProviders.isNotEmpty()) {
            Spacer(Modifier.height(18.dp))
            SsoDivider()
            Spacer(Modifier.height(10.dp))
            vm.ssoProviders.forEach { provider ->
                OutlinedButton(
                    onClick = {
                        val url = vm.ssoLoginUrl(provider.key).toUri()
                        CustomTabsIntent.Builder().build().launchUrl(context, url)
                    },
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = androidx.compose.ui.graphics.Color(0xFFF0E6CF)),
                    modifier = Modifier.fillMaxWidth().height(50.dp).padding(top = 8.dp)
                ) {
                    Text(provider.displayName, style = MaterialTheme.typography.labelLarge)
                }
            }
        }
    }
}

@Composable
private fun SsoDivider() {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.weight(1f).height(1.dp).background(SurfaceRaised))
        Text("  or  ", color = Stone, style = MaterialTheme.typography.bodySmall)
        Box(Modifier.weight(1f).height(1.dp).background(SurfaceRaised))
    }
}

@Composable
private fun SegmentedModeSwitch(mode: LoginMode, onChange: (LoginMode) -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .background(SurfaceRaised, shape = androidx.compose.foundation.shape.RoundedCornerShape(10.dp))
            .padding(4.dp)
    ) {
        SegmentedButtonLike("Log in", mode == LoginMode.LOGIN, Modifier.weight(1f)) { onChange(LoginMode.LOGIN) }
        SegmentedButtonLike("Register", mode == LoginMode.REGISTER, Modifier.weight(1f)) { onChange(LoginMode.REGISTER) }
    }
}

@Composable
private fun SegmentedButtonLike(label: String, selected: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val bg = if (selected) Brass else androidx.compose.ui.graphics.Color.Transparent
    val fg = if (selected) Ink else Stone
    Box(
        modifier
            .background(bg, shape = androidx.compose.foundation.shape.RoundedCornerShape(8.dp))
            .clickableNoIndication(onClick)
            .padding(vertical = 10.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(label, color = fg, style = MaterialTheme.typography.labelLarge)
    }
}

@Composable
private fun Modifier.clickableNoIndication(onClick: () -> Unit): Modifier = this.clickable(
    indication = null,
    interactionSource = remember { androidx.compose.foundation.interaction.MutableInteractionSource() },
    onClick = onClick
)

enum class LoginMode { LOGIN, REGISTER }
