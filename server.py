"""
Spotify MCP Server
Exposes Spotify Web API + AirPlay zone control as MCP tools.
Deploy on Render. Set env vars:
  SPOTIFY_CLIENT_ID
  SPOTIFY_CLIENT_SECRET
  SPOTIFY_REFRESH_TOKEN
"""

import os
import time
import httpx
import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

# ── Init ──────────────────────────────────────────────────────────────────────
mcp = FastMCP(
    "Spotify",
    instructions=(
        "Control Spotify playback and AirPlay speaker zones. "
        "Use get_playback to see what's playing, play/pause/next/previous to control it, "
        "get_devices to list available speakers, and set_device to switch zones."
    ),
)

SPOTIFY_API   = "https://api.spotify.com/v1"
SPOTIFY_TOKEN = "https://accounts.spotify.com/api/token"

CLIENT_ID     = os.environ["SPOTIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["SPOTIFY_REFRESH_TOKEN"]

# ── Token cache ───────────────────────────────────────────────────────────────
_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0}


async def get_token() -> str:
    """Return a valid access token, refreshing if needed."""
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 30:
        return _token_cache["access_token"]

    async with httpx.AsyncClient() as client:
        r = await client.post(
            SPOTIFY_TOKEN,
            data={
                "grant_type":    "refresh_token",
                "refresh_token": REFRESH_TOKEN,
            },
            auth=(CLIENT_ID, CLIENT_SECRET),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        data = r.json()

    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"]   = now + data.get("expires_in", 3600)
    # Some responses include a new refresh token
    if "refresh_token" in data:
        os.environ["SPOTIFY_REFRESH_TOKEN"] = data["refresh_token"]
    return _token_cache["access_token"]


async def sp(method: str, path: str, **kwargs) -> dict | None:
    """Authenticated Spotify API request. Returns parsed JSON or None."""
    token = await get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"{SPOTIFY_API}{path}"

    async with httpx.AsyncClient(timeout=10) as client:
        r = await getattr(client, method)(url, headers=headers, **kwargs)

    if r.status_code == 204:
        return {"ok": True}
    if r.status_code >= 400:
        return {"error": r.status_code, "message": r.text}
    try:
        return r.json()
    except Exception:
        return {"ok": True}


def ms_to_str(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


# ── TOOLS ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_playback() -> dict:
    """
    Get current Spotify playback state: track, artist, album, art,
    progress, duration, volume, shuffle, repeat, active device.
    """
    data = await sp("get", "/me/player?additional_types=track")
    if not data or "error" in data:
        return {"playing": False, "error": data}

    item = data.get("item") or {}
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    device  = data.get("device") or {}
    album   = item.get("album") or {}
    images  = album.get("images") or [{}]
    art_url = images[0].get("url", "") if images else ""

    return {
        "playing":      data.get("is_playing", False),
        "track":        item.get("name", "–"),
        "artist":       artists or "–",
        "album":        album.get("name", "–"),
        "art_url":      art_url,
        "progress_ms":  data.get("progress_ms", 0),
        "duration_ms":  item.get("duration_ms", 0),
        "progress_str": ms_to_str(data.get("progress_ms", 0)),
        "duration_str": ms_to_str(item.get("duration_ms", 0)),
        "volume":       device.get("volume_percent", 0),
        "shuffle":      data.get("shuffle_state", False),
        "repeat":       data.get("repeat_state", "off"),
        "device_id":    device.get("id", ""),
        "device_name":  device.get("name", "–"),
        "device_type":  device.get("type", "–"),
        "track_uri":    item.get("uri", ""),
        "context_uri":  (data.get("context") or {}).get("uri", ""),
    }


@mcp.tool()
async def play(uri: str = "", device_id: str = "") -> dict:
    """
    Resume or start playback.
    uri: optional Spotify URI (track, album, playlist, artist).
    device_id: optional target device — leave blank to use current active device.
    """
    params = {}
    if device_id:
        params["device_id"] = device_id

    body: dict = {}
    if uri:
        if uri.startswith("spotify:track:"):
            body["uris"] = [uri]
        else:
            body["context_uri"] = uri

    return await sp("put", "/me/player/play", params=params, json=body or None) or {"ok": True}


@mcp.tool()
async def pause(device_id: str = "") -> dict:
    """Pause playback."""
    params = {"device_id": device_id} if device_id else {}
    return await sp("put", "/me/player/pause", params=params) or {"ok": True}


@mcp.tool()
async def next_track(device_id: str = "") -> dict:
    """Skip to next track."""
    params = {"device_id": device_id} if device_id else {}
    return await sp("post", "/me/player/next", params=params) or {"ok": True}


@mcp.tool()
async def previous_track(device_id: str = "") -> dict:
    """Go back to previous track."""
    params = {"device_id": device_id} if device_id else {}
    return await sp("post", "/me/player/previous", params=params) or {"ok": True}


@mcp.tool()
async def set_volume(volume_percent: int, device_id: str = "") -> dict:
    """
    Set playback volume.
    volume_percent: 0–100.
    device_id: optional target device.
    """
    volume_percent = max(0, min(100, volume_percent))
    params: dict = {"volume_percent": volume_percent}
    if device_id:
        params["device_id"] = device_id
    return await sp("put", "/me/player/volume", params=params) or {"ok": True}


@mcp.tool()
async def seek(position_ms: int, device_id: str = "") -> dict:
    """Seek to position in current track. position_ms: milliseconds."""
    params: dict = {"position_ms": position_ms}
    if device_id:
        params["device_id"] = device_id
    return await sp("put", "/me/player/seek", params=params) or {"ok": True}


@mcp.tool()
async def set_shuffle(state: bool, device_id: str = "") -> dict:
    """Toggle shuffle on or off."""
    params: dict = {"state": str(state).lower()}
    if device_id:
        params["device_id"] = device_id
    return await sp("put", "/me/player/shuffle", params=params) or {"ok": True}


@mcp.tool()
async def set_repeat(state: str, device_id: str = "") -> dict:
    """
    Set repeat mode.
    state: 'track' | 'context' | 'off'
    """
    state = state if state in ("track", "context", "off") else "off"
    params: dict = {"state": state}
    if device_id:
        params["device_id"] = device_id
    return await sp("put", "/me/player/repeat", params=params) or {"ok": True}


@mcp.tool()
async def get_devices() -> dict:
    """
    List all available Spotify Connect devices, including AirPlay speakers.
    Returns name, id, type, volume, active status for each.
    """
    data = await sp("get", "/me/player/devices")
    if not data or "error" in data:
        return {"devices": [], "error": data}

    devices = [
        {
            "id":         d.get("id", ""),
            "name":       d.get("name", "–"),
            "type":       d.get("type", "–"),
            "volume":     d.get("volume_percent", 0),
            "active":     d.get("is_active", False),
            "restricted": d.get("is_restricted", False),
        }
        for d in data.get("devices", [])
    ]
    return {"devices": devices, "count": len(devices)}


@mcp.tool()
async def set_device(device_id: str, play: bool = True) -> dict:
    """
    Transfer playback to a specific device/speaker zone.
    device_id: from get_devices().
    play: whether to start playing immediately (default True).
    """
    return await sp(
        "put", "/me/player",
        json={"device_ids": [device_id], "play": play},
    ) or {"ok": True}


@mcp.tool()
async def search(query: str, types: str = "track,playlist,album", limit: int = 10) -> dict:
    """
    Search Spotify.
    query: search string.
    types: comma-separated — 'track', 'album', 'playlist', 'artist'.
    limit: max results per type (1–20).
    """
    limit = max(1, min(20, limit))
    data = await sp("get", "/search", params={"q": query, "type": types, "limit": limit})
    if not data or "error" in data:
        return {"results": {}, "error": data}

    results: dict = {}

    if "tracks" in data:
        results["tracks"] = [
            {
                "name":    t["name"],
                "artist":  ", ".join(a["name"] for a in t.get("artists", [])),
                "album":   (t.get("album") or {}).get("name", ""),
                "uri":     t["uri"],
                "art_url": ((t.get("album") or {}).get("images") or [{}])[0].get("url", ""),
                "duration_str": ms_to_str(t.get("duration_ms", 0)),
            }
            for t in data["tracks"].get("items", []) if t
        ]

    if "albums" in data:
        results["albums"] = [
            {
                "name":    a["name"],
                "artist":  ", ".join(x["name"] for x in a.get("artists", [])),
                "uri":     a["uri"],
                "art_url": (a.get("images") or [{}])[0].get("url", ""),
                "tracks":  a.get("total_tracks", 0),
            }
            for a in data["albums"].get("items", []) if a
        ]

    if "playlists" in data:
        results["playlists"] = [
            {
                "name":  p["name"],
                "owner": (p.get("owner") or {}).get("display_name", ""),
                "uri":   p["uri"],
                "art_url": (p.get("images") or [{}])[0].get("url", ""),
                "tracks": (p.get("tracks") or {}).get("total", 0),
            }
            for p in data["playlists"].get("items", []) if p
        ]

    return {"results": results}


@mcp.tool()
async def get_playlists(limit: int = 20, offset: int = 0) -> dict:
    """Get the current user's playlists."""
    limit = max(1, min(50, limit))
    data = await sp("get", "/me/playlists", params={"limit": limit, "offset": offset})
    if not data or "error" in data:
        return {"playlists": [], "error": data}

    return {
        "playlists": [
            {
                "name":    p["name"],
                "uri":     p["uri"],
                "tracks":  (p.get("tracks") or {}).get("total", 0),
                "art_url": (p.get("images") or [{}])[0].get("url", ""),
                "owner":   (p.get("owner") or {}).get("display_name", ""),
            }
            for p in data.get("items", []) if p
        ],
        "total": data.get("total", 0),
    }


@mcp.tool()
async def get_queue() -> dict:
    """Get the current playback queue (up to 20 upcoming tracks)."""
    data = await sp("get", "/me/player/queue")
    if not data or "error" in data:
        return {"queue": [], "error": data}

    currently = data.get("currently_playing") or {}
    queue = [
        {
            "name":   t["name"],
            "artist": ", ".join(a["name"] for a in t.get("artists", [])),
            "uri":    t["uri"],
            "duration_str": ms_to_str(t.get("duration_ms", 0)),
        }
        for t in (data.get("queue") or [])[:20] if t
    ]
    return {
        "currently_playing": {
            "name":   currently.get("name", "–"),
            "artist": ", ".join(a["name"] for a in currently.get("artists", [])),
        } if currently else None,
        "queue": queue,
        "count": len(queue),
    }


@mcp.tool()
async def add_to_queue(uri: str, device_id: str = "") -> dict:
    """Add a track URI to the playback queue."""
    params: dict = {"uri": uri}
    if device_id:
        params["device_id"] = device_id
    return await sp("post", "/me/player/queue", params=params) or {"ok": True}


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="streamable-http")
