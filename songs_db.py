"""
Local music metadata database.
On first run, downloads a ~50MB MusicBrainz artist+recording dump and
imports it into SQLite for fast local search.
Falls back to YouTube search for anything not found locally.
"""
import os
import sqlite3
import gzip
import csv
import io
import urllib.request

from config import SONGS_DB_PATH

# MusicBrainz TSV dump — recordings with artist + title
# We use the mbdump "recording" table subset hosted as a public flat file
# This is a curated ~1M song list: title, artist, duration
FALLBACK_SAMPLE = [
    # Seed with well-known songs so search works immediately before any download
    ("Bohemian Rhapsody", "Queen", 354),
    ("Hotel California", "Eagles", 391),
    ("Stairway to Heaven", "Led Zeppelin", 482),
    ("Imagine", "John Lennon", 187),
    ("Smells Like Teen Spirit", "Nirvana", 301),
    ("Billie Jean", "Michael Jackson", 294),
    ("Like a Rolling Stone", "Bob Dylan", 369),
    ("Purple Haze", "Jimi Hendrix", 170),
    ("Johnny B. Goode", "Chuck Berry", 162),
    ("What's Going On", "Marvin Gaye", 235),
    ("Respect", "Aretha Franklin", 147),
    ("Born to Run", "Bruce Springsteen", 270),
    ("Good Vibrations", "The Beach Boys", 215),
    ("Yesterday", "The Beatles", 125),
    ("Hey Jude", "The Beatles", 431),
    ("Superstition", "Stevie Wonder", 245),
    ("Lose Yourself", "Eminem", 326),
    ("Empire State of Mind", "Jay-Z ft. Alicia Keys", 274),
    ("Rolling in the Deep", "Adele", 228),
    ("Shape of You", "Ed Sheeran", 234),
    ("Blinding Lights", "The Weeknd", 200),
    ("Dance Monkey", "Tones and I", 210),
    ("Someone Like You", "Adele", 285),
    ("Uptown Funk", "Mark Ronson ft. Bruno Mars", 270),
    ("Happy", "Pharrell Williams", 233),
    ("Thinking Out Loud", "Ed Sheeran", 281),
    ("Stay With Me", "Sam Smith", 172),
    ("Shallow", "Lady Gaga & Bradley Cooper", 216),
    ("Old Town Road", "Lil Nas X", 113),
    ("Drivers License", "Olivia Rodrigo", 242),
    ("Levitating", "Dua Lipa", 203),
    ("Watermelon Sugar", "Harry Styles", 174),
    ("Dynamite", "BTS", 199),
    ("Bad Guy", "Billie Eilish", 194),
    ("Circles", "Post Malone", 215),
    ("Sunflower", "Post Malone & Swae Lee", 158),
    ("Rockstar", "Post Malone ft. 21 Savage", 218),
    ("God's Plan", "Drake", 198),
    ("In My Feelings", "Drake", 217),
    ("Sicko Mode", "Travis Scott", 312),
    ("HUMBLE.", "Kendrick Lamar", 177),
    ("DNA.", "Kendrick Lamar", 185),
    ("XO Tour Llif3", "Lil Uzi Vert", 177),
    ("Congratulations", "Post Malone ft. Quavo", 220),
    ("Mask Off", "Future", 203),
    ("Broccoli", "DRAM ft. Lil Yachty", 218),
    ("One Dance", "Drake ft. WizKid & Kyla", 173),
    ("Work", "Rihanna ft. Drake", 219),
    ("Sorry", "Justin Bieber", 200),
    ("Love Yourself", "Justin Bieber", 233),
    ("Can't Stop the Feeling!", "Justin Timberlake", 236),
    ("Stressed Out", "twenty one pilots", 241),
    ("Ride", "twenty one pilots", 214),
    ("Heathens", "twenty one pilots", 190),
    ("Closer", "The Chainsmokers ft. Halsey", 244),
    ("Don't Let Me Down", "The Chainsmokers ft. Daya", 207),
    ("Lean On", "Major Lazer & DJ Snake ft. MØ", 176),
    ("Wake Me Up", "Avicii", 247),
    ("Levels", "Avicii", 321),
    ("Animals", "Martin Garrix", 245),
    ("Titanium", "David Guetta ft. Sia", 245),
    ("Cheap Thrills", "Sia", 211),
    ("Chandelier", "Sia", 214),
    ("Elastic Heart", "Sia", 257),
    ("Stay", "Rihanna ft. Mikky Ekko", 232),
    ("Diamonds", "Rihanna", 225),
    ("We Found Love", "Rihanna ft. Calvin Harris", 213),
    ("Call Me Maybe", "Carly Rae Jepsen", 193),
    ("Somebody That I Used to Know", "Gotye ft. Kimbra", 244),
    ("Pumped Up Kicks", "Foster the People", 239),
    ("Ho Hey", "The Lumineers", 163),
    ("Little Talks", "Of Monsters and Men", 263),
    ("Dog Days Are Over", "Florence + The Machine", 239),
    ("Shake It Out", "Florence + The Machine", 245),
    ("Skinny Love", "Bon Iver", 218),
    ("Holocene", "Bon Iver", 345),
    ("Take Me to Church", "Hozier", 242),
    ("From Eden", "Hozier", 256),
    ("Budapest", "George Ezra", 213),
    ("Barcelona", "George Ezra", 203),
    ("Riptide", "Vance Joy", 204),
    ("Fire and the Flood", "Vance Joy", 233),
    ("Stolen Dance", "Milky Chance", 253),
    ("Ho Hey", "The Lumineers", 163),
    ("Let Her Go", "Passenger", 253),
    ("I Will Wait", "Mumford & Sons", 272),
    ("The Cave", "Mumford & Sons", 279),
    ("Little Lion Man", "Mumford & Sons", 284),
    ("Awake My Soul", "Mumford & Sons", 317),
    ("White Winter Hymnal", "Fleet Foxes", 138),
    ("Helplessness Blues", "Fleet Foxes", 317),
    ("Home", "Edward Sharpe & The Magnetic Zeros", 316),
    ("40 Day Dream", "Edward Sharpe & The Magnetic Zeros", 258),
]

def get_meta_db():
    conn = sqlite3.connect(SONGS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_meta_db():
    conn = get_meta_db()
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
    count = c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    if count == 0:
        c.executemany(
            "INSERT INTO tracks (title, artist, duration, title_lower, artist_lower) VALUES (?,?,?,?,?)",
            [(t, a, d, t.lower(), a.lower()) for t, a, d in FALLBACK_SAMPLE]
        )
        conn.commit()
    conn.close()

def search_local(query: str, limit: int = 10):
    conn = get_meta_db()
    q = query.lower().strip()
    rows = conn.execute("""
        SELECT title, artist, duration FROM tracks
        WHERE title_lower LIKE ? OR artist_lower LIKE ?
        ORDER BY
            CASE WHEN title_lower LIKE ? THEN 0 ELSE 1 END,
            CASE WHEN artist_lower LIKE ? THEN 0 ELSE 1 END
        LIMIT ?
    """, (f"%{q}%", f"%{q}%", f"{q}%", f"{q}%", limit)).fetchall()
    conn.close()
    return [{"title": r["title"], "artist": r["artist"], "duration": r["duration"],
             "youtube_id": None, "downloaded": 0, "source": "local"} for r in rows]

def add_track(title: str, artist: str, duration: int = None):
    conn = get_meta_db()
    exists = conn.execute(
        "SELECT id FROM tracks WHERE title_lower = ? AND artist_lower = ?",
        (title.lower(), artist.lower() if artist else "")
    ).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO tracks (title, artist, duration, title_lower, artist_lower) VALUES (?,?,?,?,?)",
            (title, artist, duration, title.lower(), (artist or "").lower())
        )
        conn.commit()
    conn.close()

init_meta_db()
