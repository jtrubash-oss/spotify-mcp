# Spotify MCP Server

Spotify Web API + AirPlay zone control as an MCP server, deployable on Render.

## Tools

| Tool | Description |
|---|---|
| `get_playback` | Current track, artist, album art, progress, volume, shuffle, repeat, active device |
| `play` | Resume or start a URI (track / album / playlist) on any device |
| `pause` | Pause playback |
| `next_track` | Skip forward |
| `previous_track` | Skip back |
| `set_volume` | 0–100 on any device |
| `seek` | Seek to position (ms) |
| `set_shuffle` | Toggle shuffle |
| `set_repeat` | `track` / `context` / `off` |
| `get_devices` | List all Spotify Connect + AirPlay devices |
| `set_device` | Transfer playback to a speaker zone |
| `search` | Search tracks, albums, playlists |
| `get_playlists` | Your Spotify library |
| `get_queue` | Up to 20 upcoming tracks |
| `add_to_queue` | Queue a track URI |

## Setup

### 1. Create a Spotify App
1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Create an app — any name
3. Add redirect URI: `http://localhost:8888/callback`
4. Note your **Client ID** and **Client Secret**

### 2. Get a Refresh Token

Run this one-time to get your refresh token (needs `requests` and a browser):

```bash
pip install requests
python get_token.py
```

This opens a browser, you log in to Spotify, authorise, and the script prints your `REFRESH_TOKEN`.

### 3. Deploy to Render

1. Push this folder to a GitHub repo
2. Create a new **Web Service** on Render pointing to the repo
3. Set environment variables:
   ```
   SPOTIFY_CLIENT_ID      = your_client_id
   SPOTIFY_CLIENT_SECRET  = your_client_secret
   SPOTIFY_REFRESH_TOKEN  = your_refresh_token
   ```
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn server:mcp.streamable_http_app --host 0.0.0.0 --port $PORT`

### 4. Test

```bash
curl -X POST https://your-app.onrender.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

## AirPlay Zones

AirPlay speakers that appear in Spotify Connect (e.g. HomePods, Airport Express, 
Sonos with AirPlay) will show up in `get_devices` with type `"Speaker"` or `"CastAudio"`.

Use `set_device(device_id)` to transfer playback to any zone.
