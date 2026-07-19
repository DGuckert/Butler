# Butler for Android

A native Android client for Butler, your self-hosted music server. Think of
it the way you'd think of Finamp for Jellyfin: Butler is the server that
holds your library, and this app is a proper mobile player for it, with
background playback, lock screen and notification controls, and a queue,
instead of relying on a browser tab.

This app does not talk to Spotify, YouTube, or any other outside service
directly. It only ever talks to the Butler server address you give it, the
same way a Jellyfin client only ever talks to your Jellyfin server.

## Features

- Log in or register with an invite code against any Butler server you point it at
- Background playback with a real foreground service, so music keeps playing
  when the app is closed, with controls on the lock screen and in the
  notification shade
- Library browser for everything downloaded on your server
- Search across your library and, if a song isn't downloaded yet, YouTube
- Playlists, including shared family playlists, with the ability to create,
  browse, and remove songs
- Liked songs
- Daily Mix, with a button to regenerate it on demand
- Full now playing screen with seek bar, skip controls, and an up next list
- Mini player bar that stays visible while you browse

## What's not in the app yet

A few things are still web UI only and are left for a future update:

- Spotify playlist import
- Admin tools (creating invite codes, managing users)
- Uploading or manually adding local files

You can still do all of that from the Butler web UI at your server's
address; this app is for day to day listening.

## Requirements

- A running Butler server (see the main [README](../README.md) in the
  repository root for how to set one up)
- Android 7.0 (API 24) or newer
- To build it yourself: Android Studio, or a command line setup with the
  Android SDK and JDK 17+ (the Gradle wrapper is checked in, so you don't
  need Gradle installed separately)

## Connecting to your server

On first launch, enter your Butler server's address, including the port,
for example:

```
http://192.168.1.10:8080
```

or, if you've put Butler behind a reverse proxy with a domain name:

```
https://music.example.com
```

Then log in with an existing account, or register with an invite code from
your server's admin.

The app only stores your server address and a login token on the device.
No credentials or server address are hardcoded, so the same build works for
anyone running their own Butler server.

## Building

```bash
cd android
```

Point Gradle at your Android SDK, either by setting `ANDROID_HOME` or by
creating a `local.properties` file in this folder:

```
sdk.dir=/path/to/your/android-sdk
```

Then build a debug APK with the checked-in wrapper, no separate Gradle
install needed:

```bash
./gradlew assembleDebug
```

The APK is written to `app/build/outputs/apk/debug/app-debug.apk`. Install
it with:

```bash
adb install app/build/outputs/apk/debug/app-debug.apk
```

## Architecture

- Kotlin and Jetpack Compose for the UI
- A single `ApiClient` (OkHttp plus plain JSON parsing) that wraps Butler's
  REST endpoints
- A `PlaybackService`, a Media3 `MediaSessionService` running ExoPlayer,
  which handles streaming, background playback, and system media controls.
  It attaches your session token to every stream request so authentication
  works the same way it does everywhere else in the app
- A thin `PlayerController` that connects the UI to the playback service
  through a `MediaController` and exposes playback state as a `StateFlow`

## License

Same as the rest of Butler: MIT, see the [LICENSE](../LICENSE) file in the
repository root.
