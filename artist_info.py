"""
Real artist info (bio + image), looked up on demand and cached.

Uses Wikipedia: a search biased toward "<artist> band" to dodge the most
common disambiguation trap (a place/album/word sharing the artist's name),
then the REST summary endpoint for the winning page. Best-effort — an
artist page always renders fine with no bio if the lookup fails or the
result looks like a disambiguation page.
"""
import logging
import requests

log = logging.getLogger("artist_info")

_HEADERS = {"User-Agent": "Butler-MusicServer/1.0 (self-hosted; contact: n/a)"}
_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"
_TIMEOUT = 5


def fetch_artist_info(name: str) -> dict:
    """Returns {"bio": str|None, "image": str|None, "source_url": str|None}."""
    empty = {"bio": None, "image": None, "source_url": None}
    if not name or not name.strip():
        return empty

    try:
        resp = requests.get(
            _SEARCH_URL,
            params={"action": "query", "list": "search", "srsearch": f"{name} band",
                    "format": "json", "srlimit": 1},
            headers=_HEADERS, timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        hits = resp.json().get("query", {}).get("search", [])
        title = hits[0]["title"] if hits else name

        summary = requests.get(
            _SUMMARY_URL.format(title.replace(" ", "_")),
            headers=_HEADERS, timeout=_TIMEOUT,
        )
        summary.raise_for_status()
        data = summary.json()
        if data.get("type") == "disambiguation":
            return empty

        return {
            "bio": data.get("extract"),
            "image": (data.get("thumbnail") or {}).get("source") or (data.get("originalimage") or {}).get("source"),
            "source_url": (data.get("content_urls") or {}).get("desktop", {}).get("page"),
        }
    except Exception as e:
        log.info("artist info lookup failed for %r: %s", name, e)
        return empty
