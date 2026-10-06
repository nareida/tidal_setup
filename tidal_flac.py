#!/usr/bin/env python3
"""
TIDAL FLAC Downloader — tidalapi 0.8+
Python 3.12+, Termux/Android OK

=== SETUP (first time) ===
    pip3 install tidalapi mutagen
    python3 tidal_flac.py login
    → Opens browser, shows URL
    → Authorize app → Token saved to ~/.tidal-flac-token.json

=== USAGE ===
    python3 tidal_flac.py <album-url>       # download album
    python3 tidal_flac.py <track-url>       # download track
    python3 tidal_flac.py <playlist-url>    # download playlist
    python3 tidal_flac.py <album-id>        # download by ID
    python3 tidal_flac.py login             # refresh login

Output: ~/Music/TIDAL-FLAC/
Token:  ~/.tidal-flac-token.json
"""
from __future__ import annotations

import re
import sys
import json
import urllib.request
from pathlib import Path

import tidalapi
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover

HOME = Path.home()
TOKEN_FILE = HOME / ".tidal-flac-token.json"
DOWNLOAD_DIR = HOME / "Music" / "TIDAL-FLAC"
CHUNK = 32 * 1024

# ─────────────── auth ───────────────

def load_session() -> tidalapi.Session:
    s = tidalapi.Session()

    if TOKEN_FILE.exists():
        try:
            data = json.loads(TOKEN_FILE.read_text())
            s.load_oauth_session(
                token_type=data["tokenType"],
                access_token=data["accessToken"],
                refresh_token=data.get("refreshToken"),
                is_pkce=data.get("isPkce", True),
            )
            if s.check_login():
                print(f"✅ Logged in as {s.user.first_name} {s.user.last_name}")
                return s
            else:
                print("⚠️  Token expired")
        except Exception as e:
            print(f"⚠️  Token error: {e}")

    return login(s)

def login(s: tidalapi.Session | None = None) -> tidalapi.Session:
    if s is None:
        s = tidalapi.Session()

    print("\n🔗 Open this URL in your browser to log in:")
    try:
        s.login_oauth_simple()
    except Exception as e:
        sys.exit(f"❌ Login error: {e}")

    if not s.check_login():
        sys.exit("❌ Login failed")

    TOKEN_FILE.write_text(json.dumps({
        "sessionId": s.session_id,
        "tokenType": s.token_type,
        "accessToken": s.access_token,
        "refreshToken": s.refresh_token,
        "isPkce": s.is_pkce,
    }, indent=2))
    print(f"✅ Logged in as {s.user.first_name} {s.user.last_name}")
    print(f"💾 Token saved → {TOKEN_FILE}")
    return s

# ─────────────── helpers ───────────────

def sanitize(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()

def get_meta(track) -> dict:
    album = track.album
    if hasattr(album, 'artists') and album.artists:
        artists = ", ".join(a.name for a in album.artists)
    else:
        artists = album.artist.name
    return {
        "title": track.name,
        "artist": artists,
        "album": album.name,
        "year": str(album.release_date.year) if album.release_date else "",
        "track": int(track.track_num),
        "disc": int(getattr(track, "volume_num", 1)),
    }

def cover_url(album, size: int = 1280) -> str | None:
    cover = getattr(album, "cover", None)
    if not cover:
        return None
    return f"https://resources.tidal.com/images/{cover.replace('-', '/')}/{size}x{size}.jpg"

def fetch_cover(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()
    except Exception:
        return None

def embed_flac(path: Path, meta: dict, cover_bytes: bytes | None = None):
    audio = FLAC(str(path))
    audio["title"] = meta["title"]
    audio["artist"] = meta["artist"]
    audio["album"] = meta["album"]
    audio["tracknumber"] = str(meta["track"])
    audio["discnumber"] = str(meta["disc"])
    if meta["year"]:
        audio["date"] = meta["year"]
    if cover_bytes:
        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        pic.data = cover_bytes
        audio.add_picture(pic)
    audio.save()

def embed_m4a(path: Path, meta: dict, cover_bytes: bytes | None = None):
    audio = MP4(str(path))
    audio["\xa9nam"] = meta["title"]
    audio["\xa9ART"] = meta["artist"]
    audio["\xa9alb"] = meta["album"]
    audio["trkn"] = [(meta["track"], 0)]
    if meta["year"]:
        audio["\xa9day"] = meta["year"]
    if cover_bytes:
        audio["covr"] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()

# ─────────────── download ───────────────

def _download_file(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            total = int(r.headers.get("Content-Length", 0))
            got = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = r.read(CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        pct = got * 100 // total
                        print(f"\r   ⬇ {pct}% ({got//1024}KB/{total//1024}KB)", end="", flush=True)
            print(f"\r   ✅ {dest.name} ({got//1024}KB)")
            return True
    except Exception as e:
        print(f"\r   ❌ download failed: {e}")
        return False

def download_track(session: tidalapi.Session, track_id: int, dest_dir: Path,
                   embed: bool = True):
    track = session.track(track_id)
    m = get_meta(track)
    print(f"\n🎵 {m['artist']} — {m['title']}")

    try:
        url = track.get_url()
    except Exception as e:
        print(f"   ❌ URL error: {e}")
        return

    ext = ".flac" if "flac" in url.lower() else ".m4a"
    dest = dest_dir / f"{m['track']:02d} - {m['artist']} - {m['title']}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"   ⏭ exists: {dest.name}")
        return

    if not _download_file(url, dest):
        return

    if embed:
        cover_bytes = fetch_cover(cover_url(track.album))
        if ext == ".flac":
            embed_flac(dest, m, cover_bytes)
        else:
            embed_m4a(dest, m, cover_bytes)

# ─────────────── collections ───────────────

def download_album(session: tidalapi.Session, album_id: int):
    album = session.album(album_id)
    if hasattr(album, 'artists') and album.artists:
        artists = ", ".join(a.name for a in album.artists)
    else:
        artists = album.artist.name
    name = album.name
    year = str(album.release_date.year) if album.release_date else ""
    print(f"\n💿 {artists} — {name} ({year})")
    print(f"   {album.numberOfTracks} tracks")

    safe = sanitize(f"{artists} - {name}")
    dest_dir = DOWNLOAD_DIR / safe
    dest_dir.mkdir(parents=True, exist_ok=True)

    for i, track in enumerate(album.tracks(), 1):
        print(f"\n[{i}/{album.numberOfTracks}]", end="")
        download_track(session, track.id, dest_dir)

    print(f"\n📁 Done → {dest_dir}")

def download_playlist(session: tidalapi.Session, playlist_uuid: str):
    pl = session.playlist(playlist_uuid)
    print(f"\n📋 {pl.name} ({pl.numberOfTracks} tracks)")
    safe = sanitize(pl.name)
    dest_dir = DOWNLOAD_DIR / safe
    dest_dir.mkdir(parents=True, exist_ok=True)

    for i, track in enumerate(pl.tracks(), 1):
        print(f"\n[{i}/{pl.numberOfTracks}]", end="")
        download_track(session, track.id, dest_dir)

    print(f"\n📁 Done → {dest_dir}")

# ─────────────── parser ───────────────

def parse_arg(arg: str) -> tuple[str, int | str]:
    arg = arg.strip()
    m = re.search(r'tidal\.com/browse/playlist/([a-f0-9\-]{36})', arg)
    if m:
        return "playlist", m.group(1)
    m = re.search(r'tidal\.com/browse/album/(\d+)', arg)
    if m:
        return "album", int(m.group(1))
    m = re.search(r'tidal\.com/browse/track/(\d+)', arg)
    if m:
        return "track", int(m.group(1))
    m = re.search(r'^(\d+)$', arg)
    if m:
        return "album", int(m.group(1))
    raise ValueError(f"Unrecognized: {arg}")

# ─────────────── main ───────────────

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  tidal_flac.py login")
        print("  tidal_flac.py <album/track/playlist-url>")
        print("  tidal_flac.py <album-id>")
        sys.exit(1)

    arg = sys.argv[1]
    if arg.lower() == "login":
        login()
        sys.exit(0)

    session = load_session()
    kind, item_id = parse_arg(arg)

    if kind == "album":
        download_album(session, item_id)
    elif kind == "track":
        download_track(session, item_id, DOWNLOAD_DIR)
    elif kind == "playlist":
        download_playlist(session, item_id)

if __name__ == "__main__":
    main()
