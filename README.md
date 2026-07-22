# Butler

A self-hosted music server, in the same spirit as Jellyfin or Navidrome but built
around `yt-dlp` instead of a media file library you already own. Download songs,
organize them into a personal collection, and stream them back from a web UI or
the native Android app, with playlists, likes, and multi-user family accounts.

## Features

- Web player with crossfade, queue, and playlist management
- Multi-user accounts via invite codes (one user is the admin)
- JWT-based auth (bcrypt password hashing)
- Song downloading via `yt-dlp`
- Optional Spotify OAuth integration to import your existing playlists
- Optional "Daily Mix" generator: an LLM (via [OpenRouter](https://openrouter.ai))
  suggests songs based on your listening history, which are then resolved and
  downloaded automatically

## Clients

- **Web UI**: served directly by the backend, no separate setup needed.
- **Android**: a native Kotlin/Compose client with background playback and
  lock-screen controls, in [`android/`](android/). See its own
  [README](android/README.md) for build instructions.

## Setup

### Docker (recommended)

```bash
git clone https://github.com/DGuckert/Butler.git
cd Butler
cp .env.example .env
```

Edit `.env` and set a real `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then:

```bash
docker compose up -d
```

Downloaded audio and both SQLite databases persist in a named Docker volume
(`butler_data`), so they survive rebuilds and updates. Open
`http://localhost:8080` and register the first account, it becomes the admin
and can generate invite codes for other users under `/admin`.

### Without Docker

Requires Python 3.10+ and `ffmpeg` (used by `yt-dlp` for audio extraction).

```bash
git clone https://github.com/DGuckert/Butler.git
cd Butler
bash setup.sh
```

This installs dependencies, creates a `music/` folder, and copies `.env.example`
to `.env`. Edit `.env` the same way as above, then start the server:

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

#### Running as a systemd service

`butler.service.example` is a template systemd unit. Copy it, adjust the paths/user
for your setup, and enable it:

```bash
sudo cp butler.service.example /etc/systemd/system/butler.service
sudo systemctl daemon-reload
sudo systemctl enable --now butler
```

### Daily Mix (optional)

Set `OPENROUTER_API_KEY` in `.env` to enable it, then trigger a run manually with:

```bash
python3 daily_mix.py
```

or schedule it (cron / systemd timer, or a container exec) to run once a day.

## Notes

- Downloaded audio lives in `music/` and the SQLite databases (`butler.db`,
  `songs_meta.db`) are created at runtime. Neither is tracked in git, since
  they're local to your library.
- Spotify integration is optional; leave the `SPOTIFY_*` variables blank to skip it.

## Legal

Butler downloads audio via `yt-dlp`, which is against YouTube's Terms of
Service and, for most commercially released music, copyright law in most
jurisdictions, personal-use downloading included. It's intended for a small,
private household setup, not for redistribution. Use it accordingly.

## License

MIT, see [LICENSE](LICENSE).
