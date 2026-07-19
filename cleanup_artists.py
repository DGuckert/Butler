"""
Run once to fix artist names on already-downloaded songs.
python3 cleanup_artists.py
"""
import re
import sqlite3
from config import DATABASE_URL

SUFFIXES = [" - Topic", "VEVO", " Official", " official", " Music", " Records",
            " and Nuclear Blast Records", " Nuclear Blast", "Nuclear Blast Records",
            " TV", " YouTube", " Channel"]

def clean(s):
    if not s:
        return s
    for suffix in SUFFIXES:
        s = s.replace(suffix, "")
    return s.strip()

conn = sqlite3.connect(DATABASE_URL)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT id, artist FROM songs WHERE artist IS NOT NULL").fetchall()

updated = 0
for row in rows:
    cleaned = clean(row["artist"])
    if cleaned != row["artist"]:
        conn.execute("UPDATE songs SET artist=? WHERE id=?", (cleaned, row["id"]))
        print(f"  {row['artist']} → {cleaned}")
        updated += 1

# Also mark all songs with existing files as downloaded
import os
from config import MUSIC_DIR
songs = conn.execute("SELECT youtube_id FROM songs WHERE downloaded=0 AND youtube_id IS NOT NULL").fetchall()
fixed = 0
for s in songs:
    path = os.path.join(MUSIC_DIR, f"{s['youtube_id']}.mp3")
    if os.path.exists(path):
        conn.execute("UPDATE songs SET downloaded=1 WHERE youtube_id=?", (s["youtube_id"],))
        fixed += 1

conn.commit()
conn.close()
print(f"\nCleaned {updated} artist names")
print(f"Marked {fixed} existing files as downloaded")
