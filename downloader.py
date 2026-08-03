import os
import re
import asyncio
import yt_dlp
from config import MUSIC_DIR, DATABASE_URL

_downloading = {}
_progress = {}  # youtube_id -> 0-100

def get_download_progress(youtube_id: str) -> int:
    return _progress.get(youtube_id, 0)

def _clean_artist(entry: dict) -> str:
    raw = entry.get("artist") or entry.get("creator") or entry.get("uploader") or ""
    for suffix in [" - Topic", "VEVO", " Official", " official", " Music", " Records",
                   " and Nuclear Blast Records", " Nuclear Blast", "Nuclear Blast Records",
                   " TV", " YouTube", " Channel"]:
        raw = raw.replace(suffix, "")
    return raw.strip() or entry.get("uploader", "")

def _clean_title(entry: dict) -> str:
    title = entry.get("title") or ""
    title = re.sub(r'\s*[\(\[](Official\s*(Video|Audio|Music\s*Video|Lyric\s*Video)?|Lyrics?|HD|HQ|4K|Remastered.*?|Live.*?|Audio.*?)[\)\]]', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s*[–—]\s*[A-Z][^–—]{2,}$', '', title)
    return title.strip()

def search_youtube(query: str, max_results: int = 10):
    # Use music-specific search to avoid reaction videos, covers etc
    ydl_opts = {"quiet": True, "skip_download": True, "extract_flat": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"ytsearch{max_results}:music {query}", download=False)
        entries = results.get("entries", [])
        return [
            {
                "youtube_id": e.get("id"),
                "title": _clean_title(e),
                "artist": _clean_artist(e),
                "duration": e.get("duration"),
                "thumbnail": f"https://img.youtube.com/vi/{e.get('id')}/mqdefault.jpg",
            }
            for e in entries if e.get("id")
        ]

import logging
import time

log = logging.getLogger("downloader")

_MAX_ATTEMPTS = 3

def download_song(youtube_id: str) -> str:
    existing = local_file_path(youtube_id)
    if os.path.exists(existing):
        # Make sure downloaded flag is set even for already-existing files
        _mark_downloaded(youtube_id, None)
        return existing

    last_error = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return _attempt_download(youtube_id, existing)
        except Exception as e:
            last_error = e
            log.warning("Download attempt %d/%d failed for %s: %s", attempt, _MAX_ATTEMPTS, youtube_id, e)
            if attempt < _MAX_ATTEMPTS:
                time.sleep(2 * attempt)  # brief backoff before retrying -- most failures here are transient network/rate-limit blips, not permanent

    log.error("Download failed for %s after %d attempts: %s", youtube_id, _MAX_ATTEMPTS, last_error)
    raise last_error


def _attempt_download(youtube_id: str, out_path: str) -> str:
    from settings import get_bool_setting
    lossless = get_bool_setting("lossless_downloads")

    # yt-dlp/ffmpeg write the postprocessed file in place as they encode it,
    # so a naive "does {id}.mp3 exist" check (used by the stream endpoint to
    # decide a song is ready) can see a half-written file mid-conversion.
    # Downloading under a temp name and renaming only once fully complete
    # makes the final path atomic: it either doesn't exist yet, or it's the
    # whole file, never a partial one. The temp name also carries the
    # attempt's own uniqueness so retries never collide with a previous
    # attempt's still-being-cleaned-up leftovers.
    tmp_id = f"{youtube_id}.download"

    def progress_hook(d):
        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes') or 0
            if total > 0:
                _progress[youtube_id] = int((downloaded / total) * 90)
        elif d.get('status') == 'finished':
            _progress[youtube_id] = 95

    ydl_opts = {
        "quiet": True,
        "format": "bestaudio/best",
        "outtmpl": os.path.join(MUSIC_DIR, f"{tmp_id}.%(ext)s"),
        "progress_hooks": [progress_hook],
        # yt-dlp's own internal retry knobs, on top of the outer attempt loop --
        # these cover transient fragment/network failures within a single attempt.
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "socket_timeout": 30,
    }
    if lossless:
        # Keep whatever format YouTube actually serves as "best audio"
        # (usually opus or m4a) instead of transcoding through mp3, which
        # is always lossy even at the highest mp3 bitrate. No postprocessor
        # at all means no re-encode -- the downloaded stream is the file.
        pass
    else:
        ydl_opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}
        ]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={youtube_id}", download=True)
            real_duration = info.get("duration")
            real_artist = _clean_artist(info)
            real_title = _clean_title(info)

        # Find whatever file yt-dlp actually produced under the temp name --
        # its extension depends on the source format when lossless, or is
        # always .mp3 when transcoding.
        produced = [f for f in os.listdir(MUSIC_DIR) if f.startswith(f"{tmp_id}.")]
        if not produced:
            raise RuntimeError(f"yt-dlp reported success but no output file for {tmp_id} exists")
        produced_path = os.path.join(MUSIC_DIR, produced[0])
        real_ext = produced[0].rsplit(".", 1)[-1]
        out_path = os.path.join(MUSIC_DIR, f"{youtube_id}.{real_ext}")
        os.replace(produced_path, out_path)
    finally:
        # Clean up any other stray partial files left under the temp name
        # (extra formats yt-dlp may have written before settling on one, or
        # a failed run) so they don't pile up in MUSIC_DIR.
        for f in os.listdir(MUSIC_DIR):
            if f.startswith(f"{tmp_id}."):
                try:
                    os.remove(os.path.join(MUSIC_DIR, f))
                except OSError:
                    pass

    _mark_downloaded(youtube_id, real_duration, real_artist, real_title, file_ext=real_ext)
    return out_path

def _mark_downloaded(youtube_id: str, duration, artist=None, title=None, file_ext=None):
    try:
        import sqlite3
        conn = sqlite3.connect(DATABASE_URL)
        sets, params = ["downloaded=1"], []
        if duration:
            sets.append("duration=?"); params.append(int(duration))
        if artist and title:
            sets.append("artist=?"); params.append(artist)
            sets.append("title=?"); params.append(title)
        if file_ext:
            sets.append("file_ext=?"); params.append(file_ext)
        params.append(youtube_id)
        conn.execute(f"UPDATE songs SET {', '.join(sets)} WHERE youtube_id=?", params)
        conn.commit()
        conn.close()
    except Exception:
        pass


def _known_file_ext(youtube_id: str) -> str:
    """The extension a song was actually saved with, so callers don't have
    to guess/hardcode .mp3 -- lossless downloads can be .opus, .m4a, etc."""
    try:
        import sqlite3
        conn = sqlite3.connect(DATABASE_URL)
        row = conn.execute("SELECT file_ext FROM songs WHERE youtube_id=?", (youtube_id,)).fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return "mp3"


def local_file_path(youtube_id: str) -> str:
    """Resolves a song's actual on-disk path regardless of format -- checks
    the known extension first, then falls back to scanning MUSIC_DIR for
    any file matching {youtube_id}.* in case the DB record is stale."""
    ext = _known_file_ext(youtube_id)
    path = os.path.join(MUSIC_DIR, f"{youtube_id}.{ext}")
    if os.path.exists(path):
        return path
    for f in os.listdir(MUSIC_DIR):
        if f.startswith(f"{youtube_id}.") and not f.endswith(".part") and ".download." not in f:
            return os.path.join(MUSIC_DIR, f)
    return path  # doesn't exist yet -- caller's existence check will catch that

class DownloadsDisabledError(RuntimeError):
    """Raised by ensure_downloaded when the admin has turned off automatic
    yt-dlp downloads and the requested song isn't already local. Callers
    that await this directly (like the Subsonic stream handler) can catch
    it specifically to return a clean, honest error instead of a generic
    500; fire-and-forget callers (asyncio.create_task) just let it fail
    quietly, same as any other download failure they don't currently
    handle."""
    pass


async def ensure_downloaded(youtube_id: str) -> str:
    existing = local_file_path(youtube_id)
    if os.path.exists(existing):
        _mark_downloaded(youtube_id, None)
        return existing

    from settings import get_bool_setting
    if not get_bool_setting("ytdlp_downloads_enabled"):
        raise DownloadsDisabledError(
            "Automatic downloads are disabled by the server admin, and this song isn't downloaded yet."
        )

    if youtube_id in _downloading:
        while youtube_id in _downloading:
            await asyncio.sleep(0.5)
        return local_file_path(youtube_id)
    _downloading[youtube_id] = True
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, download_song, youtube_id)
    except Exception as e:
        _downloading.pop(youtube_id, None)
        raise e
    finally:
        _downloading.pop(youtube_id, None)
    return result

def is_downloading(youtube_id: str) -> bool:
    return youtube_id in _downloading


def pick_best_match(candidates: list, expected_duration=None, tolerance: int = 2):
    """Pick the best YouTube search result for a song we already know the
    real duration of (from Spotify, iTunes, or our local metadata catalog).

    YouTube search for "<title> <artist>" often surfaces extended mixes,
    live versions, full-album uploads, or a completely different song that
    happens to share a title -- any of which throws off both playback
    length and (critically) synced lyric timing, since lyrics are timed
    against the *real* track. Comparing candidate durations against a known
    expected duration and preferring the closest one catches most of these.

    Returns (best_candidate, matched) where matched is True if the best
    candidate's duration is within `tolerance` seconds of expected_duration.
    With no expected_duration (nothing to compare against), just returns
    the top search result as before.
    """
    if not candidates:
        return None, False
    if not expected_duration:
        return candidates[0], False

    scored = [
        (abs((c.get("duration") or 0) - expected_duration), c)
        for c in candidates if c.get("duration")
    ]
    if not scored:
        return candidates[0], False

    scored.sort(key=lambda x: x[0])
    best_diff, best = scored[0]
    return best, best_diff <= tolerance
