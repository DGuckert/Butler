"""
Manual upload folder: drop audio files into UPLOADS_DIR (mounted to a real
host folder in docker-compose, so it's reachable over SMB/scp/a file
manager without touching the container) and they get indexed into the
library automatically -- no YouTube search/download step needed, since
the audio is already there.

Each uploaded file gets a synthetic id derived deterministically from its
path relative to UPLOADS_DIR, so re-scanning is idempotent: the same file
always maps to the same "youtube_id"-shaped key the rest of the app
already treats as an opaque file handle (streaming, Subsonic, playlists,
likes all key off it, none of them actually care whether it's a real
YouTube id). Files are copied into MUSIC_DIR rather than moved, so the
original upload stays put as a record of what was added.
"""
import hashlib
import logging
import os
import shutil

from mutagen import File as MutagenFile

from config import MUSIC_DIR, UPLOADS_DIR
from database import get_db

log = logging.getLogger("manual_uploads")

_AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".opus", ".ogg", ".wav", ".aac", ".wma"}


def _synthetic_id(relpath: str) -> str:
    return "local_" + hashlib.sha1(relpath.encode("utf-8")).hexdigest()[:16]


def _read_tags(path: str, fallback_name: str) -> dict:
    title, artist, duration = None, None, 0
    try:
        f = MutagenFile(path, easy=True)
        if f is not None:
            title = (f.tags.get("title", [None])[0] if f.tags else None)
            artist = (f.tags.get("artist", [None])[0] if f.tags else None)
            duration = int(f.info.length) if getattr(f, "info", None) else 0
    except Exception as e:
        log.info("Couldn't read tags from %s: %s", path, e)

    if not title or not artist:
        # "Artist - Title.ext" is the overwhelmingly common convention for
        # manually organized music folders; fall back to it when tags are
        # missing or incomplete rather than leaving the song untitled.
        stem = os.path.splitext(fallback_name)[0]
        if " - " in stem:
            guessed_artist, guessed_title = stem.split(" - ", 1)
            artist = artist or guessed_artist.strip()
            title = title or guessed_title.strip()
        else:
            title = title or stem

    return {"title": title or fallback_name, "artist": artist or "Unknown", "duration": duration}


def scan_uploads() -> dict:
    """Indexes any new files under UPLOADS_DIR. Returns a small summary dict."""
    added, skipped, failed = 0, 0, 0
    if not os.path.isdir(UPLOADS_DIR):
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        return {"added": 0, "skipped": 0, "failed": 0}

    db = get_db()
    for root, _dirs, files in os.walk(UPLOADS_DIR):
        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in _AUDIO_EXTS:
                continue
            full_path = os.path.join(root, filename)
            relpath = os.path.relpath(full_path, UPLOADS_DIR)
            synthetic_id = _synthetic_id(relpath)

            existing = db.execute(
                "SELECT id FROM songs WHERE youtube_id=?", (synthetic_id,)
            ).fetchone()
            if existing:
                skipped += 1
                continue

            try:
                tags = _read_tags(full_path, filename)
                dest_ext = ext.lstrip(".")
                dest_path = os.path.join(MUSIC_DIR, f"{synthetic_id}.{dest_ext}")
                shutil.copy2(full_path, dest_path)

                title_key = f"{tags['title'].lower()}|{tags['artist'].lower()}"
                db.execute(
                    "INSERT INTO songs (title, artist, duration, youtube_id, downloaded, title_key, file_ext) "
                    "VALUES (?,?,?,?,1,?,?)",
                    (tags["title"], tags["artist"], tags["duration"], synthetic_id, title_key, dest_ext),
                )
                db.commit()
                added += 1
            except Exception as e:
                log.warning("Failed to index upload %s: %s", relpath, e)
                failed += 1

    db.close()
    return {"added": added, "skipped": skipped, "failed": failed}
