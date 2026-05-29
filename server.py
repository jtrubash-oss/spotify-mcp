"""
Spotify MCP Server — FastAPI wrapper
Bypasses MCP transport host validation issues behind Cloudflare/Render.
Implements MCP protocol directly over HTTP+SSE.
"""

import os, time, json, asyncio
from typing import Any
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Spotify MCP")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Credentials ───────────────────────────────────────────────────────────────
SPOTIFY_API    = "https://api.spotify.com/v1"
SPOTIFY_TOKEN  = "https://accounts.spotify.com/api/token"
CLIENT_ID      = os.environ["SPOTIFY_CLIENT_ID"]
CLIENT_SECRET  = os.environ["SPOTIFY_CLIENT_SECRET"]
REFRESH_TOKEN  = os.environ["SPOTIFY_REFRESH_TOKEN"]

_token_cache: dict = {"access_token": None, "expires_at": 0}

async def get_token() -> str:
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 30:
        return _token_cache["access_token"]
    async with httpx.AsyncClient() as client:
        r = await client.post(SPOTIFY_TOKEN,
            data={"grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN},
            auth=(CLIENT_ID, CLIENT_SECRET))
        r.raise_for_status()
        data = r.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"]   = now + data.get("expires_in", 3600)
    return _token_cache["access_token"]

async def sp(method: str, path: str, **kwargs):
    token = await get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await getattr(client, method)(f"{SPOTIFY_API}{path}", headers=headers, **kwargs)
    if r.status_code == 204: return {"ok": True}
    if r.status_code >= 400: return {"error": r.status_code, "message": r.text}
    try:    return r.json()
    except: return {"ok": True}

def ms(n): s=n//1000; return f"{s//60}:{s%60:02d}"

# ── Tool implementations ───────────────────────────────────────────────────────
async def get_playback():
    data = await sp("get", "/me/player?additional_types=track")
    if not data or "error" in data: return {"playing": False}
    item = data.get("item") or {}
    device = data.get("device") or {}
    album  = item.get("album") or {}
    images = album.get("images") or [{}]
    return {
        "playing":      data.get("is_playing", False),
        "track":        item.get("name", "–"),
        "artist":       ", ".join(a["name"] for a in item.get("artists", [])),
        "album":        album.get("name", "–"),
        "art_url":      (images[0].get("url", "") if images else ""),
        "progress_ms":  data.get("progress_ms", 0),
        "duration_ms":  item.get("duration_ms", 0),
        "progress_str": ms(data.get("progress_ms", 0)),
        "duration_str": ms(item.get("duration_ms", 0)),
        "volume":       device.get("volume_percent", 0),
        "shuffle":      data.get("shuffle_state", False),
        "repeat":       data.get("repeat_state", "off"),
        "device_id":    device.get("id", ""),
        "device_name":  device.get("name", "–"),
        "device_type":  device.get("type", "–"),
        "track_uri":    item.get("uri", ""),
    }

async def play(uri="", device_id=""):
    params = {"device_id": device_id} if device_id else {}
    body: dict = {}
    if uri:
        body = {"uris": [uri]} if uri.startswith("spotify:track:") else {"context_uri": uri}
    return await sp("put", "/me/player/play", params=params, json=body or None) or {"ok": True}

async def pause(device_id=""):
    params = {"device_id": device_id} if device_id else {}
    return await sp("put", "/me/player/pause", params=params) or {"ok": True}

async def next_track(device_id=""):
    params = {"device_id": device_id} if device_id else {}
    return await sp("post", "/me/player/next", params=params) or {"ok": True}

async def previous_track(device_id=""):
    params = {"device_id": device_id} if device_id else {}
    return await sp("post", "/me/player/previous", params=params) or {"ok": True}

async def set_volume(volume_percent: int, device_id=""):
    params: dict = {"volume_percent": max(0, min(100, volume_percent))}
    if device_id: params["device_id"] = device_id
    return await sp("put", "/me/player/volume", params=params) or {"ok": True}

async def seek(position_ms: int, device_id=""):
    params: dict = {"position_ms": position_ms}
    if device_id: params["device_id"] = device_id
    return await sp("put", "/me/player/seek", params=params) or {"ok": True}

async def set_shuffle(state: bool, device_id=""):
    params: dict = {"state": str(state).lower()}
    if device_id: params["device_id"] = device_id
    return await sp("put", "/me/player/shuffle", params=params) or {"ok": True}

async def set_repeat(state: str, device_id=""):
    state = state if state in ("track", "context", "off") else "off"
    params: dict = {"state": state}
    if device_id: params["device_id"] = device_id
    return await sp("put", "/me/player/repeat", params=params) or {"ok": True}

async def get_devices():
    data = await sp("get", "/me/player/devices")
    if not data or "error" in data: return {"devices": []}
    return {"devices": [
        {"id": d.get("id",""), "name": d.get("name","–"), "type": d.get("type","–"),
         "volume": d.get("volume_percent",0), "active": d.get("is_active",False)}
        for d in data.get("devices", []) if d
    ]}

async def set_device(device_id: str, play_now: bool = True):
    return await sp("put", "/me/player", json={"device_ids": [device_id], "play": play_now}) or {"ok": True}

async def search(query: str, types: str = "track,playlist,album", limit: int = 10):
    data = await sp("get", "/search", params={"q": query, "type": types, "limit": min(20,max(1,limit))})
    if not data or "error" in data: return {"results": {}}
    results: dict = {}
    if "tracks" in data:
        results["tracks"] = [
            {"name": t["name"], "artist": ", ".join(a["name"] for a in t.get("artists",[])),
             "album": (t.get("album") or {}).get("name",""), "uri": t["uri"],
             "art_url": (((t.get("album") or {}).get("images") or [{}])[0].get("url","")),
             "duration_str": ms(t.get("duration_ms",0))}
            for t in data["tracks"].get("items",[]) if t]
    if "playlists" in data:
        results["playlists"] = [
            {"name": p["name"], "uri": p["uri"],
             "tracks": (p.get("tracks") or {}).get("total",0),
             "art_url": (p.get("images") or [{}])[0].get("url",""),
             "owner": (p.get("owner") or {}).get("display_name","")}
            for p in data["playlists"].get("items",[]) if p]
    if "albums" in data:
        results["albums"] = [
            {"name": a["name"], "artist": ", ".join(x["name"] for x in a.get("artists",[])),
             "uri": a["uri"], "art_url": (a.get("images") or [{}])[0].get("url","")}
            for a in data["albums"].get("items",[]) if a]
    return {"results": results}

async def get_playlists(limit: int = 20, offset: int = 0):
    data = await sp("get", "/me/playlists", params={"limit": min(50,max(1,limit)), "offset": offset})
    if not data or "error" in data: return {"playlists": []}
    return {"playlists": [
        {"name": p["name"], "uri": p["uri"],
         "tracks": (p.get("tracks") or {}).get("total",0),
         "art_url": (p.get("images") or [{}])[0].get("url",""),
         "owner": (p.get("owner") or {}).get("display_name","")}
        for p in data.get("items",[]) if p], "total": data.get("total",0)}

async def get_queue():
    data = await sp("get", "/me/player/queue")
    if not data or "error" in data: return {"queue": []}
    currently = data.get("currently_playing") or {}
    return {
        "currently_playing": {
            "name": currently.get("name","–"),
            "artist": ", ".join(a["name"] for a in currently.get("artists",[])),
        } if currently else None,
        "queue": [
            {"name": t["name"], "artist": ", ".join(a["name"] for a in t.get("artists",[])),
             "uri": t["uri"], "duration_str": ms(t.get("duration_ms",0))}
            for t in (data.get("queue") or [])[:20] if t]
    }

async def add_to_queue(uri: str, device_id: str = ""):
    params: dict = {"uri": uri}
    if device_id: params["device_id"] = device_id
    return await sp("post", "/me/player/queue", params=params) or {"ok": True}

# ── Tool registry ──────────────────────────────────────────────────────────────
TOOLS = {
    "get_playback":    {"fn": get_playback,    "desc": "Get current playback state, track, artist, album art, progress, volume, device."},
    "play":            {"fn": play,            "desc": "Play/resume. Args: uri (optional Spotify URI), device_id (optional)."},
    "pause":           {"fn": pause,           "desc": "Pause playback. Args: device_id (optional)."},
    "next_track":      {"fn": next_track,      "desc": "Skip to next track. Args: device_id (optional)."},
    "previous_track":  {"fn": previous_track,  "desc": "Go to previous track. Args: device_id (optional)."},
    "set_volume":      {"fn": set_volume,      "desc": "Set volume 0-100. Args: volume_percent, device_id (optional)."},
    "seek":            {"fn": seek,            "desc": "Seek to position. Args: position_ms, device_id (optional)."},
    "set_shuffle":     {"fn": set_shuffle,     "desc": "Toggle shuffle. Args: state (bool), device_id (optional)."},
    "set_repeat":      {"fn": set_repeat,      "desc": "Set repeat: track|context|off. Args: state, device_id (optional)."},
    "get_devices":     {"fn": get_devices,     "desc": "List all Spotify Connect + AirPlay devices."},
    "set_device":      {"fn": set_device,      "desc": "Transfer playback to a device/zone. Args: device_id, play_now (bool)."},
    "search":          {"fn": search,          "desc": "Search Spotify. Args: query, types (track,album,playlist), limit."},
    "get_playlists":   {"fn": get_playlists,   "desc": "Get your playlists. Args: limit, offset."},
    "get_queue":       {"fn": get_queue,       "desc": "Get current queue."},
    "add_to_queue":    {"fn": add_to_queue,    "desc": "Add track to queue. Args: uri, device_id (optional)."},
}

def tool_schema(name: str, desc: str) -> dict:
    return {"name": name, "description": desc, "inputSchema": {"type": "object", "properties": {}}}

# ── MCP Protocol ───────────────────────────────────────────────────────────────
async def handle_rpc(body: dict) -> dict:
    method = body.get("method", "")
    id_    = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "Spotify", "version": "1.0.0"},
            "instructions": "Control Spotify playback and AirPlay zones.",
        }}

    if method == "notifications/initialized":
        return None  # no response needed

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": id_, "result": {
            "tools": [tool_schema(n, t["desc"]) for n, t in TOOLS.items()]
        }}

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"Unknown tool: {name}"}}
        try:
            result = await TOOLS[name]["fn"](**args)
            return {"jsonrpc": "2.0", "id": id_, "result": {
                "content": [{"type": "text", "text": json.dumps(result)}]
            }}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32000, "message": str(e)}}

    return {"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"Method not found: {method}"}}

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
async def root(): return {"status": "ok", "service": "Spotify MCP"}

@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """Handles MCP requests over plain HTTP (SSE response format)."""
    body = await request.json()
    result = await handle_rpc(body)
    if result is None:
        return Response(status_code=204)
    # Return as SSE event stream (matches HUUM pattern)
    data = json.dumps(result)
    content = f"event: message\ndata: {data}\n\n"
    return Response(content=content, media_type="text/event-stream")

@app.get("/sse")
async def sse_endpoint(request: Request):
    """SSE stream endpoint — sends a ready ping then keeps alive."""
    async def stream():
        yield "event: endpoint\ndata: /mcp\n\n"
        while True:
            await asyncio.sleep(15)
            yield ": ping\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")
