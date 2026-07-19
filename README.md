# Butler

A self-hosted Spotify alternative. Download music with `yt-dlp`, organize it into
a personal library, and stream it from a Spotify-style web UI — crossfade, queue,
playlists, likes, and multi-user family accounts with invite codes.

## Features

- Web player with crossfade, queue, and playlist management
- Multi-user accounts via invite codes (one user is the admin)
- JWT-based auth (bcrypt password hashing)
- Song downloading via `yt-dlp`
- Optional Spotify OAuth integration to import your existing playlists
- Optional "Daily Mix" generator: an LLM (via [OpenRouter](https://openrouter.ai))
  suggests songs based on your listening history, which are then resolved and
  downloaded automatically

## Requirements

- Python 3.10+
- `ffmpeg` (required by `yt-dlp` for audio extraction)

## Setup

```bash
git clone <this-repo>
cd butler
bash setup.sh
```

This installs dependencies, creates a `music/` folder, and copies `.env.example`
to `.env`. Edit `.env` — at minimum, set a real `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then start the server:

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

Open `http://localhost:8080` and register the first account — it becomes the admin
and can generate invite codes for other users under `/admin`.

### Running as a service

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

or schedule it (cron / systemd timer) to run once a day.

## Notes

- Downloaded audio lives in `music/` and the SQLite databases (`butler.db`,
  `songs_meta.db`) are created at runtime — neither is tracked in git, since
  they're local to your library.
- Spotify integration is optional; leave the `SPOTIFY_*` variables blank to skip it.

## License

MIT — see [LICENSE](LICENSE).
