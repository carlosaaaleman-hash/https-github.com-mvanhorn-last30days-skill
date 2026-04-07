#!/usr/bin/env python3
"""
assemble.py — Faceless YouTube video assembler using FFmpeg.

Usage:
  python assemble.py --config config.json [--voiceover vo.mp3] [--clips clips/] \
                     [--thumbnail thumbnail.jpg] [--output output/] \
                     [--music music.mp3] [--preset channel_id]
  python assemble.py --serve [--port 5050]
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Channel presets
# ---------------------------------------------------------------------------

CHANNEL_PRESETS = {
    "personal_finance_en": {
        "channel_name": "Personal Finance EN",
        "format": "landscape",
        "add_captions": True,
        "background_music": True,
        "music_style": "calm ambient",
    },
    "personal_finance_es": {
        "channel_name": "Personal Finance ES",
        "format": "landscape",
        "add_captions": True,
        "background_music": True,
        "music_style": "calm ambient",
    },
    "mafia_chronicles": {
        "channel_name": "Mafia Chronicles",
        "format": "landscape",
        "add_captions": True,
        "background_music": True,
        "music_style": "dark ambient",
    },
    "stoic_mindset": {
        "channel_name": "Stoic Mindset",
        "format": "landscape",
        "add_captions": True,
        "background_music": True,
        "music_style": "calm ambient",
    },
    "wwii_untold": {
        "channel_name": "WWII Untold",
        "format": "landscape",
        "add_captions": True,
        "background_music": True,
        "music_style": "dramatic orchestral",
    },
    "future_engineered": {
        "channel_name": "Future Engineered",
        "format": "landscape",
        "add_captions": True,
        "background_music": True,
        "music_style": "electronic ambient",
    },
    "mitos_leyendas": {
        "channel_name": "Mitos y Leyendas",
        "format": "landscape",
        "add_captions": True,
        "background_music": True,
        "music_style": "mystical ambient",
    },
}

# ---------------------------------------------------------------------------
# FFmpeg / ffprobe helpers
# ---------------------------------------------------------------------------

def run_ffmpeg(args: list, description: str = "") -> None:
    """Run ffmpeg with the given argument list. Raises RuntimeError on failure."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args
    log.info("  ffmpeg: %s", description or " ".join(args[:6]))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed ({description}): {result.stderr.strip()}"
        )


def ffprobe_duration(path: str) -> float:
    """Return duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def ffprobe_video_info(path: str) -> dict:
    """Return dict with codec_name, width, height for the first video stream."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height",
        "-of", "json",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe video info failed on {path}: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        return {}
    return streams[0]


def is_valid_clip(path: str) -> bool:
    """Return True if the file has a decodable video stream."""
    try:
        info = ffprobe_video_info(path)
        return bool(info.get("codec_name"))
    except Exception as exc:
        log.warning("Clip validation failed for %s: %s", path, exc)
        return False


# ---------------------------------------------------------------------------
# Text / time helpers
# ---------------------------------------------------------------------------

def _escape_drawtext(text: str) -> str:
    """Escape characters that break FFmpeg drawtext: backslash, colon, apostrophe."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\\'")
    text = text.replace(":", "\\:")
    return text


def _seconds_to_srt_time(seconds: float) -> str:
    """Convert float seconds to SRT timestamp HH:MM:SS,mmm."""
    millis = int(round(seconds * 1000))
    h = millis // 3_600_000
    millis %= 3_600_000
    m = millis // 60_000
    millis %= 60_000
    s = millis // 1000
    ms = millis % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    """Load JSON config file; merge preset defaults if 'preset' key present."""
    with open(path) as fh:
        cfg = json.load(fh)
    preset_key = cfg.get("preset")
    if preset_key and preset_key in CHANNEL_PRESETS:
        merged = dict(CHANNEL_PRESETS[preset_key])
        merged.update(cfg)
        cfg = merged
    return cfg


# ---------------------------------------------------------------------------
# Build steps
# ---------------------------------------------------------------------------

def _make_intro(channel_name: str, tmpdir: str) -> str:
    out = os.path.join(tmpdir, "intro.mp4")
    safe_name = _escape_drawtext(channel_name)
    run_ffmpeg(
        [
            "-f", "lavfi", "-i", "color=c=black:s=1920x1080:r=30",
            "-t", "2",
            "-vf", (
                f"drawtext=text='{safe_name}':fontcolor=white:fontsize=72"
                ":x=(w-text_w)/2:y=(h-text_h)/2:borderw=3:bordercolor=black"
            ),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-an",
            out,
        ],
        "intro slate",
    )
    return out


def _make_outro(thumbnail_path: str | None, tmpdir: str, duration: int = 3) -> str:
    out = os.path.join(tmpdir, "outro.mp4")
    if thumbnail_path and os.path.isfile(thumbnail_path):
        run_ffmpeg(
            [
                "-loop", "1", "-i", thumbnail_path,
                "-t", str(duration),
                "-vf", (
                    "scale=1920:1080:force_original_aspect_ratio=increase,"
                    "crop=1920:1080,"
                    "drawtext=text='Subscribe!':fontcolor=white:fontsize=96"
                    ":x=(w-text_w)/2:y=h*0.85:borderw=4:bordercolor=black"
                ),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-an",
                out,
            ],
            "outro with thumbnail",
        )
    else:
        run_ffmpeg(
            [
                "-f", "lavfi", "-i", "color=c=#1a1a1a:s=1920x1080:r=30",
                "-t", str(duration),
                "-vf", (
                    "drawtext=text='Subscribe!':fontcolor=white:fontsize=96"
                    ":x=(w-text_w)/2:y=h*0.85:borderw=4:bordercolor=black"
                ),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-an",
                out,
            ],
            "outro dark fallback",
        )
    return out


def _trim_clip(clip_path: str, duration: float, index: int, tmpdir: str) -> str | None:
    """Trim (or loop) a clip to the given duration. Returns output path or None on failure."""
    out = os.path.join(tmpdir, f"clip_{index:03d}.mp4")
    try:
        clip_dur = ffprobe_duration(clip_path)
        scale_filter = (
            "scale=1920:1080:force_original_aspect_ratio=increase,"
            "crop=1920:1080,setsar=1"
        )
        if clip_dur < duration:
            loops = int(duration / clip_dur) + 1
            run_ffmpeg(
                [
                    "-stream_loop", str(loops),
                    "-i", clip_path,
                    "-t", str(duration),
                    "-vf", scale_filter,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-an",
                    out,
                ],
                f"loop clip {index}",
            )
        else:
            run_ffmpeg(
                [
                    "-i", clip_path,
                    "-t", str(duration),
                    "-vf", scale_filter,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-an",
                    out,
                ],
                f"trim clip {index}",
            )
        return out
    except Exception as exc:
        log.warning("Clip %d (%s) failed, skipping: %s", index, clip_path, exc)
        return None


def _concat_clips(segment_paths: list[str], tmpdir: str) -> str:
    """Write a concat list file and join all segments into raw_video.mp4."""
    list_file = os.path.join(tmpdir, "concat_list.txt")
    with open(list_file, "w") as fh:
        for p in segment_paths:
            fh.write(f"file '{p}'\n")
    out = os.path.join(tmpdir, "raw_video.mp4")
    run_ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", out],
        "concat all segments",
    )
    return out


def _mix_audio(
    video_path: str,
    voiceover_path: str,
    music_path: str | None,
    tmpdir: str,
) -> str:
    out = os.path.join(tmpdir, "mixed.mp4")
    if music_path and os.path.isfile(music_path):
        video_duration = ffprobe_duration(video_path)
        run_ffmpeg(
            [
                "-i", video_path,
                "-i", voiceover_path,
                "-stream_loop", "-1", "-i", music_path,
                "-filter_complex", (
                    "[1:a]apad[vo];"
                    f"[2:a]volume=-18dB,atrim=0:{video_duration:.3f}[music];"
                    "[vo][music]amix=inputs=2:duration=first:dropout_transition=3[aout]"
                ),
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                out,
            ],
            "mix audio with background music",
        )
    else:
        run_ffmpeg(
            [
                "-i", video_path,
                "-i", voiceover_path,
                "-filter_complex", "[1:a]apad[aout]",
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                out,
            ],
            "mix audio voiceover only",
        )
    return out


def _transcribe_and_caption(video_path: str, tmpdir: str) -> tuple[str, str]:
    """
    Transcribe audio with openai-whisper, write .srt, burn into video.
    Returns (captioned_video_path, srt_path).
    Raises on failure (caller should catch and continue).
    """
    import whisper  # lazy import

    log.info("  Transcribing with whisper…")
    model = whisper.load_model("base")

    # Extract audio for transcription
    audio_path = os.path.join(tmpdir, "audio_for_caption.mp3")
    run_ffmpeg(
        ["-i", video_path, "-vn", "-c:a", "mp3", audio_path],
        "extract audio for whisper",
    )

    result = model.transcribe(audio_path)
    segments = result.get("segments", [])

    srt_path = os.path.join(tmpdir, "captions.srt")
    with open(srt_path, "w", encoding="utf-8") as fh:
        for i, seg in enumerate(segments, 1):
            start = _seconds_to_srt_time(seg["start"])
            end = _seconds_to_srt_time(seg["end"])
            text = seg["text"].strip()
            fh.write(f"{i}\n{start} --> {end}\n{text}\n\n")

    captioned = os.path.join(tmpdir, "captioned.mp4")
    # SRT path must be escaped for FFmpeg subtitles filter on Windows paths
    safe_srt = srt_path.replace("\\", "/").replace(":", "\\:")
    run_ffmpeg(
        [
            "-i", video_path,
            "-vf", (
                f"subtitles='{safe_srt}':force_style="
                "'FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF,"
                "OutlineColour=&H00000000,Outline=2,Shadow=1,Alignment=2,MarginV=30'"
            ),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            captioned,
        ],
        "burn subtitles",
    )
    return captioned, srt_path


def _final_encode_landscape(input_path: str, output_path: str) -> None:
    run_ffmpeg(
        [
            "-i", input_path,
            "-c:v", "libx264", "-preset", "slow", "-crf", "23",
            "-vf", (
                "scale=1920:1080:force_original_aspect_ratio=decrease,"
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1"
            ),
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            output_path,
        ],
        "final landscape encode",
    )


def _final_encode_portrait(landscape_path: str, output_path: str) -> None:
    run_ffmpeg(
        [
            "-i", landscape_path,
            "-vf", (
                "scale=1920:1080,"
                "crop=608:1080:(iw-608)/2:0,"
                "scale=1080:1920,setsar=1"
            ),
            "-c:v", "libx264", "-preset", "slow", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            output_path,
        ],
        "portrait reframe",
    )


def _generate_metadata(transcript: str, config: dict, tmpdir: str) -> dict:
    """Call Claude API to generate titles, description, and tags. Returns dict."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping metadata generation.")
        return {"titles": [], "description": "", "tags": [], "note": "ANTHROPIC_API_KEY not set"}

    try:
        import anthropic  # lazy import
        client = anthropic.Anthropic(api_key=api_key)
        channel = config.get("channel_name", "")
        prompt = (
            f"You are a YouTube SEO expert for the channel '{channel}'.\n\n"
            "Given this video transcript, generate:\n"
            "1. 5 compelling title suggestions (each under 70 chars)\n"
            "2. A YouTube description (200-300 words, with timestamps if available)\n"
            "3. 15 relevant hashtags/tags\n\n"
            "Respond with valid JSON only:\n"
            '{"titles": [...], "description": "...", "tags": [...]}\n\n'
            f"TRANSCRIPT:\n{transcript[:8000]}"
        )
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as exc:
        log.error("Metadata generation failed: %s", exc)
        return {"titles": [], "description": "", "tags": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def assemble_video(
    voiceover_path: str,
    clips_dir: str,
    thumbnail_path: str | None,
    config: dict,
    output_dir: str = "output",
    music_path: str | None = None,
) -> dict:
    """
    Assemble a faceless YouTube video.

    Returns:
        dict with keys: landscape, portrait (optional), srt (optional), metadata
    """
    channel_name = config.get("channel_name", "My Channel")
    fmt = config.get("format", "landscape")
    add_captions = config.get("add_captions", False)
    use_music = config.get("background_music", False)
    outro_duration = config.get("outro_duration_seconds", 3)

    channel_slug = channel_name.lower().replace(" ", "_")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    os.makedirs(output_dir, exist_ok=True)

    # Collect and validate clips
    clips_path = Path(clips_dir)
    raw_clips = sorted(clips_path.glob("*.mp4"))
    if not raw_clips:
        raise ValueError(f"No .mp4 files found in clips directory: {clips_dir}")

    valid_clips = [str(c) for c in raw_clips if is_valid_clip(str(c))]
    if not valid_clips:
        raise ValueError("All clips failed validation — cannot assemble video.")

    log.info("[step 1/10] Validated %d/%d clips", len(valid_clips), len(raw_clips))

    # Calculate per-clip duration
    vo_duration = ffprobe_duration(voiceover_path)
    seconds_per_clip = vo_duration / len(valid_clips)
    log.info("[step 2/10] Voiceover duration=%.1fs, %.1fs per clip", vo_duration, seconds_per_clip)

    with tempfile.TemporaryDirectory() as tmpdir:
        log.info("[step 3/10] Building intro slate")
        intro = _make_intro(channel_name, tmpdir)

        log.info("[step 4/10] Building outro slate")
        outro = _make_outro(thumbnail_path, tmpdir, duration=outro_duration)

        log.info("[step 5/10] Trimming/looping %d clips", len(valid_clips))
        trimmed = []
        for idx, clip_path in enumerate(valid_clips):
            result = _trim_clip(clip_path, seconds_per_clip, idx, tmpdir)
            if result:
                trimmed.append(result)

        if not trimmed:
            raise ValueError("All clip trim operations failed.")

        log.info("[step 6/10] Concatenating %d segments", len(trimmed) + 2)
        all_segments = [intro] + trimmed + [outro]
        raw_video = _concat_clips(all_segments, tmpdir)

        log.info("[step 7/10] Mixing audio")
        mixed = _mix_audio(raw_video, voiceover_path, music_path if use_music else None, tmpdir)

        # Captions
        srt_output_path = None
        captioned = mixed
        if add_captions:
            log.info("[step 8/10] Generating captions")
            try:
                captioned, tmp_srt = _transcribe_and_caption(mixed, tmpdir)
                srt_output_path = os.path.join(
                    output_dir, f"{channel_slug}_{timestamp}.srt"
                )
                import shutil
                shutil.copy2(tmp_srt, srt_output_path)
                log.info("  Captions saved to %s", srt_output_path)
            except Exception as exc:
                log.error("Captions failed, continuing without: %s", exc)
                captioned = mixed
        else:
            log.info("[step 8/10] Captions disabled, skipping")

        log.info("[step 9/10] Final encode")
        landscape_path = os.path.join(output_dir, f"{channel_slug}_{timestamp}_landscape.mp4")
        _final_encode_landscape(captioned, landscape_path)

        portrait_path = None
        if fmt in ("portrait", "both"):
            portrait_path = os.path.join(output_dir, f"{channel_slug}_{timestamp}_portrait.mp4")
            _final_encode_portrait(landscape_path, portrait_path)

        # Metadata
        log.info("[step 10/10] Generating metadata")
        transcript_text = ""
        if srt_output_path and os.path.isfile(srt_output_path):
            with open(srt_output_path) as fh:
                transcript_text = fh.read()

        metadata = _generate_metadata(transcript_text, config, tmpdir)
        metadata["channel_name"] = channel_name
        metadata["format"] = fmt
        metadata["timestamp"] = timestamp
        metadata_path = os.path.join(output_dir, f"{channel_slug}_{timestamp}_metadata.json")
        try:
            with open(metadata_path, "w") as fh:
                json.dump(metadata, fh, indent=2)
        except Exception as exc:
            log.error("Could not save metadata: %s", exc)
            metadata_path = None

    outputs = {"landscape": landscape_path, "metadata": metadata_path}
    if portrait_path:
        outputs["portrait"] = portrait_path
    if srt_output_path:
        outputs["srt"] = srt_output_path

    log.info("Done! Outputs: %s", outputs)
    return outputs


# ---------------------------------------------------------------------------
# Flask server
# ---------------------------------------------------------------------------

def run_server(port: int = 5050) -> None:
    from flask import Flask, jsonify, request  # lazy import
    import shutil

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GB

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "presets": list(CHANNEL_PRESETS.keys())})

    @app.get("/presets")
    def presets():
        return jsonify(CHANNEL_PRESETS)

    @app.post("/assemble")
    def assemble_endpoint():
        upload_dir = tempfile.mkdtemp(prefix="assemble_upload_")
        try:
            # Config / preset
            cfg_str = request.form.get("config", "{}")
            try:
                cfg = json.loads(cfg_str)
            except json.JSONDecodeError as exc:
                return jsonify({"status": "error", "message": f"Invalid config JSON: {exc}"}), 400

            preset_key = request.form.get("preset") or cfg.get("preset")
            if preset_key and preset_key in CHANNEL_PRESETS:
                merged = dict(CHANNEL_PRESETS[preset_key])
                merged.update(cfg)
                cfg = merged

            # Save uploaded files
            def save_file(field, filename):
                f = request.files.get(field)
                if f:
                    dest = os.path.join(upload_dir, filename)
                    f.save(dest)
                    return dest
                return None

            voiceover_path = save_file("voiceover", "voiceover.mp3")
            if not voiceover_path:
                return jsonify({"status": "error", "message": "voiceover file required"}), 400

            clips_dir = os.path.join(upload_dir, "clips")
            os.makedirs(clips_dir)
            clips_files = request.files.getlist("clips")
            for i, cf in enumerate(clips_files):
                cf.save(os.path.join(clips_dir, f"clip_{i:03d}.mp4"))

            thumbnail_path = save_file("thumbnail", "thumbnail.jpg")
            music_path = save_file("music", "music.mp3")

            output_dir = os.path.join(upload_dir, "output")
            os.makedirs(output_dir)

            outputs = assemble_video(
                voiceover_path=voiceover_path,
                clips_dir=clips_dir,
                thumbnail_path=thumbnail_path,
                config=cfg,
                output_dir=output_dir,
                music_path=music_path,
            )
            return jsonify({"status": "success", "outputs": outputs})

        except Exception as exc:
            log.exception("Assembly failed")
            shutil.rmtree(upload_dir, ignore_errors=True)
            return jsonify({"status": "error", "message": str(exc)}), 500

    log.info("Starting assemble server on port %d", port)
    app.run(host="0.0.0.0", port=port)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_cli_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Assemble faceless YouTube videos with FFmpeg"
    )
    p.add_argument("--serve", action="store_true", help="Run Flask HTTP server")
    p.add_argument("--port", type=int, default=5050, help="Server port (default 5050)")
    p.add_argument("--config", help="Path to config.json")
    p.add_argument("--voiceover", default="voiceover.mp3", help="Voiceover MP3 path")
    p.add_argument("--clips", default="clips/", help="Directory of b-roll .mp4 clips")
    p.add_argument("--thumbnail", default=None, help="Optional thumbnail.jpg for outro")
    p.add_argument("--music", default=None, help="Optional background music MP3")
    p.add_argument("--output", default="output/", help="Output directory")
    p.add_argument("--preset", default=None, help="Channel preset key")
    return p


def main() -> None:
    parser = build_cli_parser()
    args = parser.parse_args()

    if args.serve:
        run_server(port=args.port)
        return

    # Load config
    cfg: dict = {}
    if args.config:
        cfg = load_config(args.config)
    elif args.preset:
        if args.preset not in CHANNEL_PRESETS:
            parser.error(f"Unknown preset '{args.preset}'. Available: {list(CHANNEL_PRESETS)}")
        cfg = dict(CHANNEL_PRESETS[args.preset])
    else:
        parser.error("Provide --config or --preset")

    # CLI flags override config values
    if args.preset and not cfg.get("preset"):
        cfg["preset"] = args.preset

    outputs = assemble_video(
        voiceover_path=args.voiceover,
        clips_dir=args.clips,
        thumbnail_path=args.thumbnail,
        config=cfg,
        output_dir=args.output,
        music_path=args.music,
    )

    print("\nOutputs:")
    for key, path in outputs.items():
        if path:
            print(f"  {key}: {path}")


if __name__ == "__main__":
    main()
