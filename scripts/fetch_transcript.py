#!/usr/bin/env python3
"""Get a timestamped transcript for a YouTube URL or a local media file.

Captions first (manual, then auto); if none, download audio and transcribe
locally (mlx-whisper on Apple Silicon, openai-whisper elsewhere).

Writes into OUT_DIR:
  meta.json       title/channel/duration/etc (URLs only)
  transcript.txt  2-minute paragraphs prefixed with [h:mm]
  status          RUNNING | DONE | NEEDS_SIGNIN | FAILED, plus a message
Exit codes: 0 done, 3 needs a signed-in browser (private/members-only), 1 failure.

Stdlib only. Run with `python3 -I`; tools are pulled on demand with uvx.
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

HALLUCINATIONS = {  # Whisper's stock output on silence/music
    "thank you.", "thank you", "thanks for watching!", "thanks for watching.",
    "thank you for watching.", "thank you for watching!", "you", ".",
    "please subscribe.", "bye.", "bye-bye.",
}
SIGNIN_RE = re.compile(
    r"private video|sign in to confirm your age|members-only|join this channel|"
    r"video is private|login required|this video is available to this channel",
    re.I,
)


def status(out, state, msg=""):
    (out / "status").write_text(f"{state}\n{msg}\n")
    print(f"[{state}] {msg}", flush=True)


def ytdlp_cmd(browser):
    cmd = ["uvx", "--from", "yt-dlp[default]", "yt-dlp", "--no-progress"]
    if not shutil.which("deno") and shutil.which("node"):
        cmd += ["--js-runtimes", "node"]  # yt-dlp needs a JS runtime for YouTube
    if browser:
        cmd += ["--cookies-from-browser", browser]
    return cmd


def run(cmd, **kw):
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def fetch_meta(url, browser):
    r = run(ytdlp_cmd(browser) + ["-J", "--no-playlist", url])
    if r.returncode != 0:
        return None, r.stderr
    return json.loads(r.stdout), ""


def has_lang(tracks, lang):
    return [k for k in (tracks or {}) if k == lang or k.startswith(lang + "-")]


def get_captions(url, browser, meta, lang, out):
    manual = has_lang(meta.get("subtitles"), lang)
    auto = has_lang(meta.get("automatic_captions"), lang)
    if not (manual or auto):
        return None
    flag = "--write-subs" if manual else "--write-auto-subs"
    # auto captions: prefer the "-orig" track (source language, not translated)
    keys = manual or sorted(auto, key=lambda k: (not k.endswith("-orig"), k != lang))
    r = run(ytdlp_cmd(browser) + [
        "--skip-download", flag, "--sub-langs", keys[0], "--sub-format", "vtt",
        "--no-playlist", "-o", str(out / "captions.%(ext)s"), url])
    files = sorted(out.glob("captions*.vtt"))
    if r.returncode != 0 or not files:
        print(r.stderr[-2000:], file=sys.stderr)
        return None
    return files[0], ("manual" if manual else "auto") + f" captions ({keys[0]})"


def ensure_ffmpeg(out):
    if shutil.which("ffmpeg"):
        return os.environ["PATH"]
    r = run(["uvx", "--from", "imageio-ffmpeg", "python", "-c",
             "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"])
    if r.returncode != 0:
        raise RuntimeError("could not get ffmpeg: " + r.stderr[-500:])
    bindir = out / "bin"
    bindir.mkdir(exist_ok=True)
    link = bindir / "ffmpeg"
    if not link.exists():
        link.symlink_to(r.stdout.strip())  # whisper calls `ffmpeg` by name
    return f"{bindir}{os.pathsep}{os.environ['PATH']}"


def transcribe(audio, out, lang):
    env = dict(os.environ, PATH=ensure_ffmpeg(out))
    apple = sys.platform == "darwin" and platform.machine() == "arm64"
    if apple:
        cmd = ["uvx", "--from", "mlx-whisper", "mlx_whisper", str(audio),
               "--model", "mlx-community/whisper-large-v3-turbo",
               "--output-format", "vtt", "--output-dir", str(out),
               "--condition-on-previous-text", "False"]
    else:  # ponytail: CPU/CUDA fallback, slow on long audio; swap in faster-whisper if it matters
        cmd = ["uvx", "--from", "openai-whisper", "whisper", str(audio),
               "--model", "turbo", "--output_format", "vtt",
               "--output_dir", str(out), "--condition_on_previous_text", "False"]
    if lang != "auto":
        cmd += ["--language", lang]
    print("$", " ".join(cmd), flush=True)
    if subprocess.run(cmd, env=env).returncode != 0:
        raise RuntimeError("transcription failed (see log)")
    return out / (Path(audio).stem + ".vtt")


AUDIO_CODECS = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "m4a": ["-c:a", "aac", "-b:a", "160k"],
    "wav": ["-c:a", "pcm_s16le"],
}


def export_audio(src, out, fmt, title):
    """Write the audio track of src as <title>.<fmt> in out; returns the path."""
    path = ensure_ffmpeg(out)
    safe = re.sub(r"[^\w\- ]+", "", title or "").strip()[:80] or "audio"
    dst = out / f"{safe}.{fmt}"
    r = run([shutil.which("ffmpeg", path=path), "-loglevel", "error", "-y", "-i", str(src),
             "-vn", *AUDIO_CODECS[fmt], str(dst)])
    if r.returncode != 0:
        raise RuntimeError("audio export failed: " + r.stderr.strip()[-500:])
    return dst


def probe_duration(src, out):
    """Seconds of media in src (from ffmpeg's banner), or None."""
    path = ensure_ffmpeg(out)
    r = run([shutil.which("ffmpeg", path=path), "-hide_banner", "-i", str(src)])
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return round(int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])) if m else None


def ts(s):
    p = s.strip().split(":")
    return sum(float(x) * 60 ** i for i, x in enumerate(reversed(p)))


def parse_vtt(path):
    cues, cur = [], None
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if "-->" in line:
            a, b = line.split("-->")
            cur = [ts(a), ts(b.split()[0]), []]
            cues.append(cur)
        elif cur is not None and line.strip():
            t = re.sub(r"<[^>]+>", "", line).strip()  # strip <c>, <00:00:01.000> tags
            if t:
                cur[2].append(t)
        elif not line.strip():
            cur = None
    return [(a, b, " ".join(t)) for a, b, t in cues if t]


def clean(cues):
    """Drop silence hallucinations and the rolling repeats of YouTube auto-captions."""
    keep, recent = [], []
    for a, b, t in cues:
        low = t.lower().strip()
        if low in HALLUCINATIONS and (b - a >= 5 or (keep and keep[-1][2].lower() == low)):
            continue
        if t in recent:
            continue
        recent = (recent + [t])[-4:]
        keep.append((a, b, t))
    out, prev = [], None  # collapse 3+ identical consecutive lines
    run_len = 0
    for c in keep:
        run_len = run_len + 1 if c[2] == prev else 1
        prev = c[2]
        if run_len <= 2:
            out.append(c)
    return out


def paragraphs(cues, minutes=2):
    blocks = {}
    for a, _, t in cues:
        blocks.setdefault(int(a // (60 * minutes)), []).append(t)
    lines = []
    for k in sorted(blocks):
        m = k * minutes
        lines.append(f"[{m // 60}:{m % 60:02d}] " + " ".join(blocks[k]))
    return "\n\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="YouTube URL or local audio/video file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--browser", help="chrome|firefox|safari|edge|brave[:PROFILE] "
                    "- only for videos the signed-in account may view")
    ap.add_argument("--lang", default="en", help="caption/transcription language, or 'auto'")
    ap.add_argument("--force-audio", action="store_true", help="skip captions, transcribe audio")
    ap.add_argument("--audio", choices=sorted(AUDIO_CODECS),
                    help="also save the audio track as <title>.<format>")
    args = ap.parse_args()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    status(out, "RUNNING", args.source)
    try:
        src = Path(args.source).expanduser()
        if src.exists():
            audio = src.resolve()
            meta = {"title": src.stem, "source": str(audio)}
            secs = probe_duration(audio, out)
            if secs is not None:
                h, rem = divmod(secs, 3600)
                m, s = divmod(rem, 60)
                meta["duration"] = secs
                meta["duration_string"] = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            vtt, how = transcribe(audio, out, args.lang), "local whisper transcription"
        else:
            full, err = fetch_meta(args.source, args.browser)
            if full is None:
                if SIGNIN_RE.search(err):
                    status(out, "NEEDS_SIGNIN", err.strip().splitlines()[-1])
                    return 3
                raise RuntimeError(err.strip().splitlines()[-1] if err.strip() else "yt-dlp failed")
            meta = {k: full.get(k) for k in (
                "id", "title", "channel", "uploader", "upload_date", "duration_string",
                "duration", "webpage_url", "availability", "description", "chapters")}
            got = None if args.force_audio else get_captions(
                args.source, args.browser, full, args.lang, out)
            audio = None
            if not got or args.audio:
                r = run(ytdlp_cmd(args.browser) + [
                    "-f", "bestaudio[ext=m4a]/bestaudio", "--no-playlist",
                    "-o", str(out / "audio.%(ext)s"), args.source])
                audio = next(iter(sorted(out.glob("audio.*"))), None)
                if r.returncode != 0 or audio is None:
                    raise RuntimeError("audio download failed: " + r.stderr.strip()[-500:])
            if got:
                vtt, how = got
            else:
                vtt, how = transcribe(audio, out, args.lang), "local whisper transcription"
        meta["transcript_source"] = how
        if args.audio:
            meta["audio_file"] = str(export_audio(audio, out, args.audio, meta.get("title")))
        (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        text = paragraphs(clean(parse_vtt(vtt)))
        (out / "transcript.txt").write_text(text, encoding="utf-8")
        status(out, "DONE", f"{len(text.split())} words via {how}")
        return 0
    except Exception as e:  # report every failure through the status file
        status(out, "FAILED", str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
