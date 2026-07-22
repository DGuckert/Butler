"""
Real album-art lookup, instead of falling back to a YouTube video frame.

Uses the free, keyless iTunes Search API (no auth, no rate-limit key needed
for our volume). Upgrades the default 100x100 thumbnail to a 600x600 image.
Falls back to the YouTube thumbnail only if no match is found or the
lookup fails for any reason (network hiccup, no internet, etc).
"""
import logging
import requests

log = logging.getLogger("album_art")

_ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
_TIMEOUT = 3  # seconds — never let a slow lookup stall song insertion


def _youtube_frame(youtube_id: str) -> str:
    return f"https://img.youtube.com/vi/{youtube_id}/mqdefault.jpg"


def find_album_art(title: str, artist: str, youtube_id: str) -> str:
    """Best-effort real album art for (title, artist). Always returns a URL —
    falls back to the YouTube video-frame thumbnail if nothing better is found."""
    fallback = _youtube_frame(youtube_id)
    if not title:
        return fallback

    term = f"{title} {artist}".strip() if artist else title
    try:
        resp = requests.get(
            _ITUNES_SEARCH_URL,
            params={"term": term, "media": "music", "entity": "song", "limit": 1},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            return fallback
        art = results[0].get("artworkUrl100")
        if not art:
            return fallback
        # iTunes serves multiple resolutions off the same path; swap in a
        # larger size than the default 100x100 thumbnail.
        return art.replace("100x100bb", "600x600bb")
    except Exception as e:
        log.info("album art lookup failed for %r: %s", term, e)
        return fallback
