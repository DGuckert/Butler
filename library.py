"""
In-place library indexing.

Point LIBRARY_DIR at an existing, already-organized music collection (the
kind Lidarr or beets maintains, usually on a NAS) and Butler indexes and
streams the files right where they are. Nothing is copied, moved, renamed,
tagged or deleted -- the mount can (and should) be read-only. Everything
Butler needs to remember (database, extracted cover art, downloads) lives in
its own /data, never inside the library.

Compared with manual_uploads.py (which copies files into MUSIC_DIR so Butler
owns a second copy), this module only ever *reads* the source files:

  * each file's identity is its path relative to LIBRARY_DIR, stored in
    songs.library_path; streaming resolves it back to a real path on demand
  * embedded tags are read with mutagen: title, artist, album, album artist,
    track and disc number, duration
  * covers come from the embedded picture (extracted once into
    COVER_CACHE_DIR) or, failing that, a cover.jpg/folder.jpg next to the
    tracks (served straight from the library, no copy)
  * rescans are incremental: a file is only re-read when its mtime or size
    changed; new files are added, changed files updated, and files that
    disappeared are hidden (not deleted) so likes and playlists survive a
    NAS hiccup, a Lidarr upgrade, or a rename
"""
import base64
import hashlib
import logging
import os
import re
import threading
import time

from mutagen import File as MutagenFile

from config import (
    COVER_CACHE_DIR, LIBRARY_DIR, LIBRARY_PRUNE_DAYS,
)
from database import get_db

log = logging.getLogger("library")

AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".opus", ".ogg", ".wav", ".aac", ".wma"}
_COVER_STEMS = ("cover", "folder", "front", "albumart", "album")
_COVER_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_COMMIT_EVERY = 200

_scan_lock = threading.Lock()


def enabled() -> bool:
    return bool(LIBRARY_DIR)


def _synthetic_id(relpath: str) -> str:
    return "lib_" + hashlib.sha1(relpath.encode("utf-8", "surrogateescape")).hexdigest()[:16]


def resolve(relpath: str):
    """Absolute path for a library-relative path, or None if it would
    escape LIBRARY_DIR (defense in depth -- relpaths come from our own DB)."""
    if not enabled() or not relpath:
        return None
    root = os.path.normpath(LIBRARY_DIR)
    full = os.path.normpath(os.path.join(root, relpath))
    if full != root and not full.startswith(root + os.sep):
        return None
    return full


# ── tags ────────────────────────────────────────────────────────────────

def _first(tags, key):
    try:
        v = tags.get(key)
    except Exception:
        return None
    if not v:
        return None
    s = str(v[0] if isinstance(v, (list, tuple)) else v).strip()
    return s or None


def _num(value):
    """'3', '3/12' -> 3. Anything unparseable -> None."""
    if not value:
        return None
    m = re.match(r"\s*(\d+)", str(value))
    return int(m.group(1)) if m else None


def read_tags(full_path: str, relpath: str) -> dict:
    parts = relpath.split(os.sep)
    stem = os.path.splitext(parts[-1])[0]
    title = artist = album = album_artist = None
    track = disc = None
    duration = 0
    try:
        f = MutagenFile(full_path, easy=True)
        if f is not None:
            tags = f.tags or {}
            title = _first(tags, "title")
            artist = _first(tags, "artist")
            album = _first(tags, "album")
            album_artist = _first(tags, "albumartist")
            track = _num(_first(tags, "tracknumber"))
            disc = _num(_first(tags, "discnumber"))
            duration = int(f.info.length) if getattr(f, "info", None) else 0
    except Exception as e:
        log.info("Couldn't read tags from %s: %s", relpath, e)

    # Untagged files: lean on the Artist/Album/NN - Title layout Lidarr and
    # friends produce, rather than leaving the track nameless.
    m = re.match(r"^(\d{1,3})\s*[-._ ]\s*(.+)$", stem)
    if m:
        track = track or int(m.group(1))
        stem = m.group(2)
    if not title:
        title = stem
    if not album and len(parts) >= 3:
        album = parts[-2]
    if not artist:
        artist = album_artist or (parts[-3] if len(parts) >= 3 else None) or "Unknown"
    return {
        "title": title, "artist": artist, "album": album,
        "album_artist": album_artist, "track_number": track,
        "disc_number": disc, "duration": duration,
    }


# ── cover art ───────────────────────────────────────────────────────────

def _extract_embedded(full_path: str):
    """(bytes, ext) of the first embedded picture, or None."""
    try:
        f = MutagenFile(full_path)
    except Exception:
        return None
    if f is None:
        return None
    try:
        pics = getattr(f, "pictures", None)  # FLAC
        if pics:
            return pics[0].data, ("png" if "png" in (pics[0].mime or "") else "jpg")
        tags = f.tags
        if tags is None:
            return None
        if hasattr(tags, "getall"):  # ID3
            apic = tags.getall("APIC")
            if apic:
                return apic[0].data, ("png" if "png" in (apic[0].mime or "") else "jpg")
        if "covr" in tags and tags["covr"]:  # MP4/M4A
            c = tags["covr"][0]
            return bytes(c), ("png" if getattr(c, "imageformat", None) == 14 else "jpg")
        if "metadata_block_picture" in tags:  # Ogg Vorbis/Opus
            from mutagen.flac import Picture
            pic = Picture(base64.b64decode(tags["metadata_block_picture"][0]))
            return pic.data, ("png" if "png" in (pic.mime or "") else "jpg")
    except Exception as e:
        log.info("Couldn't extract embedded art from %s: %s", full_path, e)
    return None


def _folder_cover(dirpath: str):
    try:
        names = os.listdir(dirpath)
    except OSError:
        return None
    by_lower = {n.lower(): n for n in names}
    for stem in _COVER_STEMS:
        for ext in _COVER_EXTS:
            if stem + ext in by_lower:
                return os.path.join(dirpath, by_lower[stem + ext])
    return None


def cover_for(library_path: str, album: str):
    """(file_path, media_type) for a track's cover, or None. Embedded art is
    extracted once per album into COVER_CACHE_DIR; folder art is served from
    the library directly."""
    full = resolve(library_path)
    if not full:
        return None
    key = hashlib.sha1(
        f"{os.path.dirname(library_path)}\x1f{(album or '').lower()}".encode("utf-8", "surrogateescape")
    ).hexdigest()
    for ext in ("jpg", "png"):
        cached = os.path.join(COVER_CACHE_DIR, f"{key}.{ext}")
        if os.path.exists(cached):
            return cached, f"image/{'png' if ext == 'png' else 'jpeg'}"
    marker = os.path.join(COVER_CACHE_DIR, f"{key}.none")
    if os.path.exists(marker):
        folder = _folder_cover(os.path.dirname(full))
        return (folder, _media_type(folder)) if folder else None

    embedded = _extract_embedded(full)
    try:
        os.makedirs(COVER_CACHE_DIR, exist_ok=True)
        if embedded:
            data, ext = embedded
            out = os.path.join(COVER_CACHE_DIR, f"{key}.{ext}")
            with open(out, "wb") as fh:
                fh.write(data)
            return out, f"image/{'png' if ext == 'png' else 'jpeg'}"
        open(marker, "w").close()  # don't re-parse this album's tags on every request
    except OSError as e:
        log.warning("Couldn't cache cover art in %s: %s", COVER_CACHE_DIR, e)
    folder = _folder_cover(os.path.dirname(full))
    return (folder, _media_type(folder)) if folder else None


def _media_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")


# ── scanning ────────────────────────────────────────────────────────────

def _title_key(title, artist):
    return f"{(title or '').lower()}|{(artist or '').lower()}"


def _walk():
    """Yields (relpath, full_path, stat) for every audio file. Returns
    (files, had_errors) -- had_errors means some directory couldn't be read,
    so absence of a file can't be trusted."""
    files, errors = [], []
    root = os.path.normpath(LIBRARY_DIR)
    for dirpath, _dirs, names in os.walk(root, onerror=errors.append):
        for name in names:
            if os.path.splitext(name)[1].lower() not in AUDIO_EXTS:
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError as e:
                errors.append(e)
                continue
            files.append((os.path.relpath(full, root), full, st))
    return files, bool(errors)


def scan_library() -> dict:
    """Incremental scan of LIBRARY_DIR. Safe to call from any thread; a
    second concurrent call returns immediately instead of piling up."""
    summary = {"added": 0, "updated": 0, "missing": 0, "restored": 0,
               "unchanged": 0, "failed": 0, "pruned": 0, "skipped": None}
    if not enabled():
        summary["skipped"] = "LIBRARY_DIR not set"
        return summary
    if not os.path.isdir(LIBRARY_DIR):
        log.warning("LIBRARY_DIR %s is not a directory (NAS unmounted?) -- scan skipped, nothing marked missing", LIBRARY_DIR)
        summary["skipped"] = "LIBRARY_DIR not available"
        return summary
    if not _scan_lock.acquire(blocking=False):
        summary["skipped"] = "scan already running"
        return summary
    try:
        return _scan(summary)
    finally:
        _scan_lock.release()


def _scan(summary: dict) -> dict:
    files, had_errors = _walk()
    db = get_db()
    try:
        known = {
            r["library_path"]: r for r in db.execute(
                "SELECT id, youtube_id, title, album, duration, title_key, library_path, "
                "library_mtime_ns, library_size, library_missing_since FROM songs "
                "WHERE library_path IS NOT NULL"
            ).fetchall()
        }
        seen = set()
        pending = 0
        new_files = []

        for relpath, full, st in files:
            seen.add(relpath)
            row = known.get(relpath)
            if row is None:
                new_files.append((relpath, full, st))
                continue
            if (row["library_mtime_ns"] == st.st_mtime_ns and row["library_size"] == st.st_size
                    and not row["library_missing_since"]):
                summary["unchanged"] += 1
                continue
            try:
                t = read_tags(full, relpath)
                db.execute(
                    "UPDATE songs SET title=?, artist=?, album=?, album_artist=?, track_number=?, "
                    "disc_number=?, duration=?, title_key=?, file_ext=?, downloaded=1, "
                    "library_mtime_ns=?, library_size=?, library_missing_since=NULL WHERE id=?",
                    (t["title"], t["artist"], t["album"], t["album_artist"], t["track_number"],
                     t["disc_number"], t["duration"], _title_key(t["title"], t["artist"]),
                     os.path.splitext(relpath)[1].lstrip(".").lower(),
                     st.st_mtime_ns, st.st_size, row["id"]),
                )
                summary["restored" if row["library_missing_since"] else "updated"] += 1
                pending += 1
            except Exception as e:
                log.warning("Failed to update %s: %s", relpath, e)
                summary["failed"] += 1
            if pending >= _COMMIT_EVERY:
                db.commit(); pending = 0

        # Files that vanished: only trust that when the walk was clean.
        if had_errors:
            log.warning("Some library directories were unreadable -- skipping missing-file detection this pass")
        else:
            missing_rows = [r for p, r in known.items() if p not in seen and not r["library_missing_since"]]
            if missing_rows and not seen:
                log.warning("Library scan found zero audio files but %d are indexed -- looks like an empty/unmounted "
                            "share, leaving everything as-is", len(missing_rows))
            else:
                for r in missing_rows:
                    db.execute("UPDATE songs SET downloaded=0, library_missing_since=CURRENT_TIMESTAMP WHERE id=?", (r["id"],))
                    summary["missing"] += 1
                    pending += 1

        # New paths: a renamed/upgraded file (Lidarr does this a lot) is the
        # same track as a missing one -- adopt the old row so likes, history
        # and playlist entries follow the file instead of being orphaned.
        adopt = {}
        for p, r in known.items():
            if p not in seen and (r["library_missing_since"] or not had_errors):
                adopt.setdefault((r["title_key"], (r["album"] or "").lower(), r["duration"] or 0), []).append(r)

        for relpath, full, st in new_files:
            try:
                t = read_tags(full, relpath)
                tk = _title_key(t["title"], t["artist"])
                ext = os.path.splitext(relpath)[1].lstrip(".").lower()
                match = None
                for dur in (t["duration"], t["duration"] - 1, t["duration"] + 1):
                    cands = adopt.get((tk, (t["album"] or "").lower(), dur))
                    if cands:
                        match = cands.pop(0)
                        break
                if match is not None:
                    if not match["library_missing_since"]:
                        summary["missing"] -= 1  # flagged earlier this pass, but it was only renamed
                    db.execute(
                        "UPDATE songs SET title=?, artist=?, album=?, album_artist=?, track_number=?, "
                        "disc_number=?, duration=?, title_key=?, file_ext=?, downloaded=1, library_path=?, "
                        "library_mtime_ns=?, library_size=?, library_missing_since=NULL WHERE id=?",
                        (t["title"], t["artist"], t["album"], t["album_artist"], t["track_number"],
                         t["disc_number"], t["duration"], tk, ext, relpath,
                         st.st_mtime_ns, st.st_size, match["id"]),
                    )
                    summary["restored"] += 1
                else:
                    yid = _synthetic_id(relpath)
                    if db.execute("SELECT 1 FROM songs WHERE youtube_id=?", (yid,)).fetchone():
                        # An adopted (renamed) row still carries the id this path
                        # would hash to -- take a distinct one instead of stealing it.
                        yid = _synthetic_id(f"{relpath}\0{st.st_size}\0{st.st_mtime_ns}")
                    cur = db.execute(
                        "INSERT OR IGNORE INTO songs (title, artist, album, album_artist, track_number, disc_number, "
                        "duration, youtube_id, downloaded, title_key, file_ext, thumbnail, library_path, "
                        "library_mtime_ns, library_size) VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?,?,?)",
                        (t["title"], t["artist"], t["album"], t["album_artist"], t["track_number"],
                         t["disc_number"], t["duration"], yid, tk, ext, f"/songs/art/{yid}",
                         relpath, st.st_mtime_ns, st.st_size),
                    )
                    summary["added" if cur.rowcount else "failed"] += 1
                pending += 1
            except Exception as e:
                log.warning("Failed to index %s: %s", relpath, e)
                summary["failed"] += 1
            if pending >= _COMMIT_EVERY:
                db.commit(); pending = 0

        if LIBRARY_PRUNE_DAYS > 0 and not had_errors and seen:
            summary["pruned"] = _prune(db)
        db.commit()
    finally:
        db.close()
    return summary


def _prune(db) -> int:
    """Drop DB rows (never files) for tracks gone longer than LIBRARY_PRUNE_DAYS."""
    rows = db.execute(
        "SELECT id FROM songs WHERE library_path IS NOT NULL AND library_missing_since IS NOT NULL "
        "AND library_missing_since < datetime('now', ?)", (f"-{int(LIBRARY_PRUNE_DAYS)} days",)
    ).fetchall()
    for r in rows:
        for tbl in ("liked_songs", "play_history", "playlist_songs"):
            db.execute(f"DELETE FROM {tbl} WHERE song_id=?", (r["id"],))
        db.execute("DELETE FROM songs WHERE id=?", (r["id"],))
    return len(rows)
