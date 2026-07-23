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

def download_song(youtube_id: str) -> str:
    out_path = os.path.join(MUSIC_DIR, f"{youtube_id}.mp3")
    if os.path.exists(out_path):
        # Make sure downloaded flag is set even for already-existing files
        _mark_downloaded(youtube_id, None)
        return out_path

    # yt-dlp/ffmpeg write the postprocessed file in place as they encode it,
    # so a naive "does {id}.mp3 exist" check (used by the stream endpoint to
    # decide a song is ready) can see a half-written file mid-conversion.
    # Downloading under a temp name and renaming only once fully complete
    # makes out_path atomic: it either doesn't exist yet, or it's the whole
    # file, never a partial one.
    tmp_id = f"{youtube_id}.download"
    tmp_path = os.path.join(MUSIC_DIR, f"{tmp_id}.mp3")

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
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}],
        "progress_hooks": [progress_hook],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={youtube_id}", download=True)
            real_duration = info.get("duration")
            real_artist = _clean_artist(info)
            real_title = _clean_title(info)

        os.replace(tmp_path, out_path)
    finally:
        # Clean up any stray partial files left under the temp name
        # (other extensions yt-dlp may have created before conversion, or
        # a failed run) so they don't pile up in MUSIC_DIR.
        for f in os.listdir(MUSIC_DIR):
            if f.startswith(f"{tmp_id}."):
                try:
                    os.remove(os.path.join(MUSIC_DIR, f))
                except OSError:
                    pass

    _mark_downloaded(youtube_id, real_duration, real_artist, real_title)
    return out_path

def _mark_downloaded(youtube_id: str, duration, artist=None, title=None):
    try:
        import sqlite3
        conn = sqlite3.connect(DATABASE_URL)
        if duration and artist and title:
            conn.execute(
                "UPDATE songs SET downloaded=1, duration=?, artist=?, title=? WHERE youtube_id=?",
                (int(duration), artist, title, youtube_id)
            )
        elif duration:
            conn.execute("UPDATE songs SET downloaded=1, duration=? WHERE youtube_id=?",
                         (int(duration), youtube_id))
        else:
            conn.execute("UPDATE songs SET downloaded=1 WHERE youtube_id=?", (youtube_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass

async def ensure_downloaded(youtube_id: str) -> str:
    out_path = os.path.join(MUSIC_DIR, f"{youtube_id}.mp3")
    if os.path.exists(out_path):
        _mark_downloaded(youtube_id, None)
        return out_path
    if youtube_id in _downloading:
        while youtube_id in _downloading:
            await asyncio.sleep(0.5)
        return out_path
    _downloading[youtube_id] = True
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, download_song, youtube_id)
    except Exception as e:
        _downloading.pop(youtube_id, None)
        raise e
    finally:
        _downloading.pop(youtube_id, None)
    return out_path

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
