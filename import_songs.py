"""
Run once: python3 import_songs.py /tmp/songs.csv
Imports track_name, track_artist, duration_ms into songs_meta.db
"""
import sys
import csv
import sqlite3
import os

CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else '/tmp/songs.csv'
DB_PATH = os.path.join(os.path.dirname(__file__), 'songs_meta.db')

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("""
    CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        artist TEXT,
        duration INTEGER,
        title_lower TEXT,
        artist_lower TEXT
    )
""")
c.execute("CREATE INDEX IF NOT EXISTS idx_title ON tracks(title_lower)")
c.execute("CREATE INDEX IF NOT EXISTS idx_artist ON tracks(artist_lower)")

# Clear existing seed data
c.execute("DELETE FROM tracks")

seen = set()
batch = []
skipped = 0
imported = 0

with open(CSV_PATH, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        title = row.get('track_name', '').strip()
        artist = row.get('track_artist', '').strip()
        dur_ms = row.get('duration_ms', '0').strip()

        if not title or not artist:
            skipped += 1
            continue

        # Dedupe by lowercase title+artist
        key = (title.lower(), artist.lower())
        if key in seen:
            skipped += 1
            continue
        seen.add(key)

        try:
            duration = int(float(dur_ms)) // 1000
        except:
            duration = 0

        batch.append((title, artist, duration, title.lower(), artist.lower()))
        imported += 1

        if len(batch) >= 1000:
            c.executemany(
                "INSERT INTO tracks (title, artist, duration, title_lower, artist_lower) VALUES (?,?,?,?,?)",
                batch
            )
            conn.commit()
            batch = []

if batch:
    c.executemany(
        "INSERT INTO tracks (title, artist, duration, title_lower, artist_lower) VALUES (?,?,?,?,?)",
        batch
    )
    conn.commit()

total = c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
conn.close()

print(f"Imported: {imported}")
print(f"Skipped (dupes/empty): {skipped}")
print(f"Total in DB: {total}")
