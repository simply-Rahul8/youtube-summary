# youtube-summary

A [Claude Code](https://claude.com/claude-code) skill that turns a YouTube video, or a local video/audio file, into a detailed section-by-section PDF summary. It can also save the audio as mp3/m4a/wav.

- Uses the video's captions when they exist. Otherwise it downloads the audio and transcribes it locally with Whisper, so it also handles caption-less live streams, lectures and multi-hour recordings.
- Works for public and unlisted videos. For a private or members-only video, it works only when **your own signed-in account can already watch it**: it reads that browser's cookies after asking you first. It never tries to get around access controls.
- Long jobs run detached, so closing the session doesn't kill a 4-hour transcription.

## Install

```bash
git clone https://github.com/simply-Rahul8/youtube-summary ~/.claude/skills/youtube-summary
```

Start a new Claude Code session. Then either run `/youtube-summary <url>` or just ask, for example: "summarize this video into a PDF: https://youtu.be/...".

## Requirements

- [uv](https://docs.astral.sh/uv/). yt-dlp, mlx-whisper, ffmpeg and reportlab are fetched on demand through `uvx` / `uv run`, so nothing is installed globally.
- Node 22+ or Deno, which yt-dlp needs as a JavaScript runtime for YouTube.
- Python 3.9+.
- An Apple Silicon Mac for fast local transcription (mlx-whisper large-v3-turbo, roughly 4–5 minutes per hour of audio on an 8 GB M-series Mac). Other machines fall back to openai-whisper, which is slower.

## What's in here

| Path | What it is |
|---|---|
| `SKILL.md` | The skill instructions Claude follows |
| `scripts/fetch_transcript.py` | Captions or audio download, Whisper transcription, hallucination filter, optional audio export |
| `scripts/md_to_pdf.py` | Markdown to A4 PDF renderer |
| `evals/` | Test prompts, trigger-description tests and the grader used while developing the skill |
| `docs/research.md` | Survey of existing tools and access methods that led to building this |

## Responsible use

Only process videos you're allowed to watch, and keep downloaded media for personal use. YouTube's Terms of Service restrict downloading, so check them yourself. yt-dlp's docs warn that automated use of a signed-in account can get it rate-limited or banned. For your own uploads, YouTube Studio's download or Google Takeout are the safe routes, and the skill accepts those files directly.

## License

MIT, see [LICENSE](LICENSE).
