# YouTube Faceless Video Assembler

A pure Python + FFmpeg pipeline that assembles narration-over-b-roll YouTube videos from
ElevenLabs voiceovers and Pexels b-roll clips. Supports CLI and HTTP (Flask) modes for
n8n automation.

---

## Dependencies

### System: FFmpeg

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt update && sudo apt install -y ffmpeg

# Verify
ffmpeg -version
```

### Python packages

```bash
pip install openai-whisper flask anthropic requests
```

> **Minimum Python version**: 3.10 (uses `str | None` union syntax)

---

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Optional | AI-generated titles/description/tags |
| `PORT` | Optional | Flask server port (default `5050`) |

---

## Quick start (CLI)

### Using a preset

```bash
python scripts/assemble.py \
  --preset personal_finance_en \
  --voiceover voiceover.mp3 \
  --clips clips/ \
  --thumbnail thumbnail.jpg \
  --music ambient.mp3
```

### Using a config file

```bash
python scripts/assemble.py \
  --config scripts/config.example.json \
  --voiceover voiceover.mp3 \
  --clips clips/ \
  --output output/
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--config` | — | Path to config.json |
| `--preset` | — | Channel preset key (see below) |
| `--voiceover` | `voiceover.mp3` | ElevenLabs narration MP3 |
| `--clips` | `clips/` | Directory of b-roll .mp4 files |
| `--thumbnail` | — | Optional outro thumbnail JPG |
| `--music` | — | Optional background ambient MP3 |
| `--output` | `output/` | Output directory |
| `--serve` | — | Start Flask HTTP server |
| `--port` | `5050` | Flask server port |

---

## Config file format

```json
{
  "channel_name": "Personal Finance EN",
  "format": "both",
  "add_captions": true,
  "background_music": true,
  "outro_duration_seconds": 5,
  "music_style": "calm ambient",
  "preset": "personal_finance_en"
}
```

| Field | Values | Description |
|---|---|---|
| `channel_name` | string | Appears on intro slate |
| `format` | `landscape` / `portrait` / `both` | Output format(s) |
| `add_captions` | bool | Burn Whisper subtitles |
| `background_music` | bool | Mix ambient track at -18dB |
| `outro_duration_seconds` | int | Outro slate length (default 3) |
| `preset` | string | Merge preset defaults |

---

## Channel presets

| Preset key | Channel name | Music style |
|---|---|---|
| `personal_finance_en` | Personal Finance EN | calm ambient |
| `personal_finance_es` | Personal Finance ES | calm ambient |
| `mafia_chronicles` | Mafia Chronicles | dark ambient |
| `stoic_mindset` | Stoic Mindset | calm ambient |
| `wwii_untold` | WWII Untold | dramatic orchestral |
| `future_engineered` | Future Engineered | electronic ambient |
| `mitos_leyendas` | Mitos y Leyendas | mystical ambient |

> **Note**: Presets define channel name and flags. You still supply your own music MP3
> via `--music` (the `music_style` field is informational only).

---

## Output files

```
output/
  personal_finance_en_20240115_143022_landscape.mp4   ← main YouTube video
  personal_finance_en_20240115_143022_portrait.mp4    ← Shorts/Reels version
  personal_finance_en_20240115_143022.srt             ← subtitle file
  personal_finance_en_20240115_143022_metadata.json   ← AI-generated metadata
```

**metadata.json** structure (when `ANTHROPIC_API_KEY` is set):

```json
{
  "channel_name": "Personal Finance EN",
  "format": "both",
  "timestamp": "20240115_143022",
  "titles": [
    "5 Money Habits That Changed My Life",
    "..."
  ],
  "description": "Full YouTube description with CTA...",
  "tags": ["personal finance", "money tips", "..."]
}
```

---

## VPS deployment for n8n

### 1. Upload the script

```bash
scp scripts/assemble.py user@your-vps:/opt/assembler/assemble.py
```

### 2. Install dependencies on the VPS

```bash
ssh user@your-vps
sudo apt install -y ffmpeg python3-pip
pip3 install openai-whisper flask anthropic
```

### 3. Create a systemd service

```ini
# /etc/systemd/system/assembler.service
[Unit]
Description=YouTube Video Assembler
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/assembler
Environment=ANTHROPIC_API_KEY=sk-ant-...
Environment=PORT=5050
ExecStart=/usr/bin/python3 /opt/assembler/assemble.py --serve --port 5050
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable assembler
sudo systemctl start assembler
sudo systemctl status assembler
```

### 4. nginx reverse proxy (optional)

```nginx
server {
    listen 80;
    server_name assembler.yourdomain.com;

    client_max_body_size 2G;
    proxy_read_timeout 900;
    proxy_send_timeout 900;

    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## n8n HTTP Request node setup

Add an **HTTP Request** node with:

| Setting | Value |
|---|---|
| Method | `POST` |
| URL | `http://your-vps:5050/assemble` |
| Body Content Type | `Form-Data (Multipart)` |
| Send Body | ✅ |

**Form-Data fields:**

| Field name | Type | Value |
|---|---|---|
| `voiceover` | File/Binary | Binary data from ElevenLabs node |
| `clips` | File/Binary | First clip binary |
| `clips` | File/Binary | Second clip binary (repeat per clip) |
| `thumbnail` | File/Binary | Leonardo AI image binary (optional) |
| `music` | File/Binary | Ambient MP3 binary (optional) |
| `preset` | String | `personal_finance_en` |
| `config` | String | See JSON below |

**Config JSON to paste as string value:**

```json
{"format": "both", "add_captions": true, "background_music": true}
```

**Tip**: Use n8n's **Split In Batches** or **Loop Over Items** nodes to attach multiple
clip files to the `clips` field — n8n supports sending multiple files with the same
field name in multipart requests.

### Check server health from n8n

Add a separate HTTP Request node:
- Method: `GET`
- URL: `http://your-vps:5050/health`

Expected response: `{"status": "ok", "presets": ["personal_finance_en", ...]}`

---

## How it works (pipeline)

```
voiceover.mp3 ──► ffprobe duration
clips/*.mp4   ──► validate → trim/loop to equal duration
                ┌─────────────────────────────────────┐
                │ intro (2s) + clips + outro (3s)      │
                │ FFmpeg concat demuxer (no re-encode) │
                └─────────────────────────────────────┘
                          ▼
             mix audio (voiceover + optional -18dB music)
                          ▼
            [optional] Whisper → SRT → burn subtitles
                          ▼
       final encode: H.264 CRF23 / AAC 192k / faststart
                          ▼
              landscape 1920×1080  +  portrait 1080×1920
                          ▼
           Claude API → titles / description / tags → .json
```

---

## Troubleshooting

**`ffmpeg: command not found`** — install FFmpeg (see Dependencies above).

**Corrupt clips are silently skipped** — the script validates each clip with `ffprobe`
before processing. Corrupt files log a warning and the next clip is reused.

**Captions fail / `No module named 'whisper'`** — run `pip install openai-whisper`.
The first run downloads the Whisper `base` model (~150 MB). Assembly continues without
captions if Whisper fails.

**`ANTHROPIC_API_KEY not set`** — metadata.json is still written, but `titles`,
`description`, and `tags` will be empty. Set the env var to enable AI metadata.

**Portrait output looks zoomed in** — this is by design. The portrait reframe crops the
center 608px of the 1920px-wide landscape frame (a standard 9:16 center crop). Use
portrait-native clips if you need full-frame coverage.

**n8n times out** — increase the HTTP Request node timeout. A 10-minute video with
captions can take 5–15 minutes on a small VPS. Add `proxy_read_timeout 900;` to nginx.
