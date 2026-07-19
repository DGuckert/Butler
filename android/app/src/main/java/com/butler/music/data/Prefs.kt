package com.butler.music.data

import android.content.Context
import android.content.SharedPreferences

/**
 * Small wrapper around SharedPreferences for the handful of values Butler
 * needs to remember: which server to talk to, and the logged-in user's
 * session token.
 */
class Prefs(context: Context) {
    private val sp: SharedPreferences =
        context.getSharedPreferences("butler_prefs", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = sp.getString(KEY_SERVER_URL, "") ?: ""
        set(value) = sp.edit().putString(KEY_SERVER_URL, value.trimEnd('/')).apply()

    var token: String?
        get() = sp.getString(KEY_TOKEN, null)
        set(value) = sp.edit().putString(KEY_TOKEN, value).apply()

    var username: String?
        get() = sp.getString(KEY_USERNAME, null)
        set(value) = sp.edit().putString(KEY_USERNAME, value).apply()

    val isLoggedIn: Boolean
        get() = !token.isNullOrBlank() && serverUrl.isNotBlank()

    fun clearSession() {
        sp.edit().remove(KEY_TOKEN).remove(KEY_USERNAME).apply()
    }

    companion object {
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_TOKEN = "token"
        private const val KEY_USERNAME = "username"
    }
}
