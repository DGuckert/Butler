# Contributing to Butler

Butler is a small, hobby-scale self-hosted music server. Contributions are
welcome, but keep in mind it's built and maintained by one person in their
spare time, so response times will vary.

## Reporting bugs

Open an issue with:

- What you did
- What you expected
- What actually happened
- Your Butler version (or commit hash) and how you're running it (bare
  metal, Docker, systemd service, etc.)

## Development setup

Backend:

```bash
bash setup.sh
uvicorn main:app --reload
```

or with Docker:

```bash
cp .env.example .env   # set SECRET_KEY
docker compose up --build
```

Android client:

```bash
cd android
./gradlew assembleDebug
```

Both are covered in more detail in the root [README](README.md) and
[android/README.md](android/README.md).

## Pull requests

- Keep PRs focused on one change. Smaller PRs get reviewed faster.
- Match the existing code style (the backend is plain FastAPI with no
  particular framework conventions beyond what's already there; the Android
  client follows the patterns in `android/app/src/main/java/com/butler/music`).
- If you change an API endpoint, check whether the Android client or the
  web UI (`static/index.html`) needs a matching update.
- Describe what you tested. There's no formal test suite yet, so manual
  verification steps in the PR description are genuinely useful.

## Scope

Butler downloads audio via `yt-dlp`. Contributions that make this more
reliable or configurable are welcome; contributions aimed specifically at
circumventing platform protections beyond what `yt-dlp` already does are
not, since the project's stance is "small private household use," not
"redistribution tool." See the Legal note in the README.
