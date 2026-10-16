"""YouTube Music play counts + IDs per artist.

There is no official YouTube Music API. The "22M plays" numbers in the YT Music UI come from
the same internal endpoint `ytmusicapi` talks to, so this app uses it (unofficial, may break
when YouTube changes its web client).
"""
import asyncio
import json
import logging
import os
import re
import time
import urllib.request

from ytmusicapi import YTMusic

yt = YTMusic()  # unauthenticated is enough for public artist pages
logger = logging.getLogger(__name__)

CACHE_TTL = int(os.getenv("CACHE_TTL", 6 * 3600))
YT_API_KEY = os.getenv("YT_API_KEY")
_cache: dict[str, tuple[float, dict]] = {}
_gate = asyncio.Semaphore(4)  # be polite: at most 4 artists in flight
CHANNEL_RE = re.compile(r"(UC[\w-]{22})")
UNITS = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def parse_plays(text) -> int | None:
    """'22M plays' -> 22_000_000 (YT Music rounds, so this is approximate above 1K)."""
    m = re.match(r"\s*([\d.,]+)\s*([KMB]?)", str(text or ""), re.I)
    if not m:
        return None
    return int(float(m.group(1).replace(",", "")) * UNITS[m.group(2).upper()])


def resolve_artist(query: str) -> str:
    """Accepts an artist name, a channel/browse ID (UC...), or a music.youtube.com channel URL."""
    found = CHANNEL_RE.search(query)
    if found:
        return found.group(1)
    hits = yt.search(query, filter="artists", limit=5)
    if not hits:
        raise LookupError(f"No artist found for '{query}'")
    exact = [h for h in hits if h["artist"].lower() == query.strip().lower()]
    return (exact or hits)[0]["browseId"]


def youtube_view_counts(video_ids: list[str]) -> dict[str, int]:
    """Official Data API v3 fallback, 50 IDs per request, 1 quota unit each."""
    out: dict[str, int] = {}
    for i in range(0, len(video_ids), 50):
        ids = ",".join(video_ids[i : i + 50])
        url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={ids}&key={YT_API_KEY}"
        with urllib.request.urlopen(url, timeout=15) as r:
            for item in json.load(r).get("items", []):
                out[item["id"]] = int(item["statistics"].get("viewCount", 0))
    return out


def ytmusic_view_counts(video_ids: list[str]) -> dict[str, int]:
    """Fetch video view counts for tracks whose Music playlist response omits plays."""
    out: dict[str, int] = {}
    for video_id in video_ids:
        try:
            song = yt.get_song(video_id)
            raw_count = (song.get("videoDetails") or {}).get("viewCount")
            count = parse_plays(raw_count)
            if count is not None:
                out[video_id] = count
        except Exception:
            logger.warning("Could not fetch view count for video %s", video_id, exc_info=True)
    return out


def ytmusic_playlist_counts(playlist_id: str) -> dict[str, str]:
    """Extract the play-count column from a YouTube Music playlist response."""
    browse_id = playlist_id if playlist_id.startswith("VL") else "VL" + playlist_id
    try:
        response = yt._send_request("browse", {"browseId": browse_id})
    except Exception:
        logger.warning("Could not fetch YouTube Music playlist %s", playlist_id, exc_info=True)
        return {}

    counts: dict[str, str] = {}

    def walk(value) -> None:
        if isinstance(value, dict):
            renderer = value.get("musicResponsiveListItemRenderer")
            if renderer:
                columns = renderer.get("flexColumns") or []
                video_id = None
                if columns:
                    runs = ((columns[0].get("musicResponsiveListItemFlexColumnRenderer") or {})
                            .get("text", {}).get("runs", []))
                    for run in runs:
                        endpoint = run.get("navigationEndpoint") or {}
                        video_id = (endpoint.get("watchEndpoint") or {}).get("videoId")
                        if video_id:
                            break
                if video_id and len(columns) > 2:
                    count_column = columns[2].get("musicResponsiveListItemFlexColumnRenderer") or {}
                    runs = (count_column.get("text") or {}).get("runs") or []
                    text = "".join(run.get("text", "") for run in runs)
                    if parse_plays(text) is not None:
                        counts[video_id] = text
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(response)
    return counts


def fetch_artist(query: str) -> dict:
    browse_id = resolve_artist(query)
    artist = yt.get_artist(browse_id)
    section = artist.get("songs") or {}
    playlist_counts: dict[str, str] = {}
    if section.get("browseId"):  # the full "Top songs" page, not just the 5-10 preview rows
        playlist_id = section["browseId"]
        playlist_counts = ytmusic_playlist_counts(playlist_id)
        tracks = yt.get_playlist(playlist_id, limit=None).get("tracks", [])
    else:
        tracks = section.get("results", [])

    songs, seen = [], set()
    for t in tracks:
        vid = t.get("videoId")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        album = t.get("album") or {}
        songs.append(
            {
                "title": t.get("title"),
                "video_id": vid,
                "artists": [{"name": a.get("name"), "id": a.get("id")} for a in t.get("artists") or []],
                "album": album.get("name"),
                "album_id": album.get("id"),
                "plays_text": playlist_counts.get(vid) or t.get("views"),
                "plays": parse_plays(playlist_counts.get(vid) or t.get("views")),
                "duration": t.get("duration"),
                "thumbnail": (t.get("thumbnails") or [{}])[-1].get("url"),
                "explicit": bool(t.get("isExplicit")),
                "source": "ytmusic",
            }
        )

    missing = [s for s in songs if s["plays"] is None]
    if missing:
        counts = ytmusic_view_counts([s["video_id"] for s in missing])
        for s in missing:
            if s["video_id"] in counts:
                s["plays"], s["source"] = counts[s["video_id"]], "youtube_view_count"

    missing = [s for s in songs if s["plays"] is None]
    if missing and YT_API_KEY:
        try:
            counts = youtube_view_counts([s["video_id"] for s in missing])
            for s in missing:
                if s["video_id"] in counts:
                    s["plays"], s["source"] = counts[s["video_id"]], "youtube_data_api"
        except Exception:
            logger.warning("YouTube Data API fallback failed for %s", query, exc_info=True)

    songs.sort(key=lambda s: s["plays"] or -1, reverse=True)
    return {
        "query": query,
        "artist": {
            "name": artist.get("name"),
            "id": artist.get("channelId") or browse_id,
            "thumbnail": (artist.get("thumbnails") or [{}])[-1].get("url"),
            "subscribers": artist.get("subscribers"),
        },
        "total_plays": sum(s["plays"] or 0 for s in songs),
        "songs": songs,
    }


async def get_artist_cached(query: str) -> dict:
    key = query.strip().lower()
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    async with _gate:
        data = await asyncio.to_thread(fetch_artist, query.strip())  # ytmusicapi is blocking
    _cache[key] = (time.time(), data)
    return data
