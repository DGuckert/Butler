package com.butler.music

import android.app.Application
import com.butler.music.data.DownloadManager
import com.butler.music.data.Prefs
import com.butler.music.network.ApiClient

class ButlerApp : Application() {
    lateinit var prefs: Prefs
        private set
    lateinit var api: ApiClient
        private set
    lateinit var downloads: DownloadManager
        private set

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        api = ApiClient(prefs)
        downloads = DownloadManager(this)
    }
}
