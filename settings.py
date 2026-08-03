"""Tiny server-wide key/value settings store, admin-controlled.

Distinct from per-user settings (scrobbling) -- these apply to the whole
server, e.g. whether new downloads get converted to mp3 or kept in their
original format.
"""
from database import get_db

DEFAULTS = {
    "lossless_downloads": "0",
    # Auto-download via yt-dlp when a song is played/searched but not yet
    # local. Defaults on (existing behavior) -- an admin can flip this off
    # to freeze the library to whatever's already downloaded or manually
    # uploaded, without touching yt-dlp's presence/config at all.
    "ytdlp_downloads_enabled": "1",
}


def get_setting(key: str) -> str:
    db = get_db()
    row = db.execute("SELECT value FROM server_settings WHERE key=?", (key,)).fetchone()
    db.close()
    if row is not None:
        return row["value"]
    return DEFAULTS.get(key, "")


def get_bool_setting(key: str) -> bool:
    return get_setting(key) == "1"


def set_setting(key: str, value: str):
    db = get_db()
    db.execute(
        "INSERT INTO server_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    db.commit()
    db.close()
