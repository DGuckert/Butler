<p align="center">
  <img src="docs/logo/butler-mark.svg" width="96" alt="Butler logo" />
</p>

<h1 align="center">Butler</h1>

<p align="center">
  <a href="https://github.com/DGuckert/Butler/releases/latest">
    <img src="https://img.shields.io/github/v/release/DGuckert/Butler?label=latest%20release&color=C89B3C" alt="Latest release" />
  </a>
</p>

A self-hosted Spotify alternative. Download music with `yt-dlp`, organize it into a personal library, and stream it from a Spotify-style web UI with crossfade, queue, playlists, synced lyrics, and multi-user family accounts.

## Showcase

<p align="center">
  <img src="docs/screenshots/web-desktop.jpg" width="720" alt="Butler web player on desktop" />
</p>

<p align="center"><em>Web player — desktop</em></p>

<p align="center">
  <img src="docs/screenshots/android-home.jpg" width="200" alt="Home tab: Recently Played, Recommended For You, Daily Mix" />
  <img src="docs/screenshots/android-search.jpg" width="200" alt="Search results" />
  <img src="docs/screenshots/android-library.jpg" width="200" alt="Your Library: playlists, liked songs, downloads" />
  <img src="docs/screenshots/android-nowplaying.jpg" width="200" alt="Now Playing with live synced lyrics" />
</p>

<p align="center"><em>Android app — Home, Search, Library, and synced-lyrics Now Playing screen</em></p>

## Features

### Core Playback & Library
- **Web player** with crossfade, queue management, and persistent playback state
- **Album art** with fallback to artist images and graceful degradation
- **Cross-device playback control** — control what's playing from any device
- **Artist pages** with biography (via MusicBrainz)

### Music Discovery & Personalization
- **Daily Mix generator** — LLM-powered (via [OpenRouter](https://openrouter.ai)) suggestions based on your listening history, auto-resolved and downloaded
- **Spotify OAuth integration** to import existing playlists
- **ListenBrainz scrobbling** — sync your listening history

### Lyrics & Metadata
- **Live synced lyrics** on web and Android (YouTube + LyricFind resolution with 2-second tolerance)
- **Album art caching** with automatic cleanup
- **Song metadata** auto-enriched from downloads and existing files

### Multi-User & Admin
- **Multi-user accounts** via invite codes (admin can generate and manage)
- **JWT-based auth** with bcrypt password hashing
- **Admin panel** for library management, settings, and user control

### Music Management
- **Download via yt-dlp** with retry logic for resilience
- **Manual upload folder** with auto-indexing (mp3, m4a, flac, opus, ogg, wav, aac)
- **Lossless download setting** for admin-controlled audio quality
- **Automatic folder scanning** every few minutes, or manual "Scan Now" trigger

### API & Compatibility
- **Subsonic API compatibility** for third-party client support
- **Offline downloads** on Android with sync across devices

### Mobile (Android)
- **Native Kotlin/Compose app** with 1:1 feature parity to web
- **Offline playback** with selective download management
- **Android Auto support** for in-car control
- **Real-time playback sync** across devices

## Requirements

- Python 3.10+
- `ffmpeg` (required by `yt-dlp` for audio extraction)
- Docker (for containerized deployment) or systemd (for native service)

## Quick Start

### Docker (Recommended)

```bash
git clone https://github.com/DGuckert/Butler.git
cd Butler
docker compose build butler
docker compose up -d
```

Open `http://localhost:8080`, register the first account (becomes admin), and manage users/settings via `/admin`.

### Native Installation

```bash
git clone https://github.com/DGuckert/Butler.git
cd Butler
bash setup.sh
```

Edit `.env` — at minimum, set a real `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then start:

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

### Systemd Service (Optional)

`butler.service.example` is a template systemd unit:

```bash
sudo cp butler.service.example /etc/systemd/system/butler.service
# Edit paths/user as needed
sudo systemctl daemon-reload
sudo systemctl enable --now butler
```

## Configuration

All settings via `.env`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `SECRET_KEY` | JWT signing key (generate with `secrets.token_urlsafe(48)`) | Required |
| `OPENROUTER_API_KEY` | Daily Mix LLM suggestions | (optional) |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | OAuth playlist import | (optional) |
| `LISTENBRAINZ_USER_TOKEN` | Scrobbling support | (optional) |
| `ADMIN_LOSSLESS_DOWNLOAD` | Force lossless downloads (if source available) | false |

## Features in Detail

### Daily Mix

Enable by setting `OPENROUTER_API_KEY` in `.env`. Trigger manually:

```bash
python3 daily_mix.py
```

Or schedule via cron/systemd timer for automatic daily suggestions.

### Manual Music Library

Drop files into `uploads/` (any of mp3, m4a, flac, opus, ogg, wav, aac). Butler scans automatically every few minutes, reading embedded tags or parsing "Artist - Title.ext" filenames.

Admins can also trigger immediate scan from **Family/Admin → Scan Now**.

### Offline Download (Android)

Selectively download tracks to your device. Downloaded content syncs across all your devices via the backend.

### Subsonic API

Use any Subsonic-compatible client (Subtracks, Dsub, etc.) to connect to your Butler instance.

## Android App

**[Download the latest release](https://github.com/DGuckert/Butler/releases/latest)** — signed APK, ready to sideload. Point it at your own Butler server on first launch.

Features:
- Full playback control with offline support
- Real-time sync with web player
- Android Auto for car control
- Persistent queue and playback state

### Building from source

```bash
cd android
./gradlew :app:assembleDebug
```

Debug APK is at `app/build/outputs/apk/debug/app-debug.apk`. Install on your device or emulator.

## Architecture

- **Backend**: FastAPI (Python 3.10+) with SQLite
- **Web Frontend**: Vanilla JS (no framework)
- **Android App**: Kotlin with Jetpack Compose
- **Deployment**: Docker or systemd

Databases (`butler.db`, `songs_meta.db`) and `music/` folder are created at runtime and not tracked in git — they're local to your library.

## Development & Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT — see [LICENSE](LICENSE).

---
