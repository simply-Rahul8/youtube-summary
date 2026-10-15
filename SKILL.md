---
name: youtube-summary
description: Turn a YouTube video (public, unlisted, or a private/members-only one the user's own signed-in account can already view) or a local video/audio recording into a detailed, section-by-section summary document, delivered as a PDF, and can also extract the audio track as mp3/m4a/wav. Uses captions when they exist and otherwise downloads the audio and transcribes it locally with Whisper, so it works on caption-less live streams, lectures, webinars, meetings and multi-hour recordings. Use this whenever the user shares a youtube.com / youtu.be / youtube.com/live link (or a .mp4/.m4a/.mp3/.webm file) and wants a summary, notes, study guide, transcript, "every detail", key takeaways, a PDF/document of it, or the audio/mp3 from it, even if they don't say "transcribe".
---

# YouTube summary

Pipeline: **get transcript -> read all of it -> write a structured Markdown summary -> render PDF.**
`scripts/fetch_transcript.py` handles the first step and `scripts/md_to_pdf.py` the last. You write the summary in between.

## 1. Access: only what the user may already watch

- Public and unlisted videos need no sign-in. Always try those first without cookies.
- A private or members-only video makes the script exit with `NEEDS_SIGNIN`. You can only proceed by reading cookies from a browser where **the user's own account that has been granted access** is signed in.
  - Ask which browser (and profile, if they use more than one) before passing `--browser`. Cookies are their credentials.
  - Tell them that yt-dlp's docs warn that automated use of a signed-in account can get it rate-limited or banned. For their own uploads, YouTube Studio download or Google Takeout is the risk-free alternative, and the script accepts the resulting local file.
- Never try to get around privacy settings, region locks, DRM or paywalls, and never use someone else's account. If the user's account can't view the video, say so and stop.
- "This video is private" even with `--browser` usually means the account with access isn't the browser's default signed-in account. Suggest `--browser chrome:"Profile 2"`, or signing in with that account in a fresh profile.

## 2. Get the transcript (detached: long videos take a while)

Use a durable working folder, never a session scratchpad, which can be wiped mid-job: `~/youtube-summaries/<video-id-or-file-stem>/`.
Start the job detached so it survives the session ending:

```bash
OUT=~/youtube-summaries/<id>; mkdir -p "$OUT"
nohup python3 -I ~/.claude/skills/youtube-summary/scripts/fetch_transcript.py "<url-or-file>" \
  --out "$OUT" [--browser chrome] [--lang en|auto] [--force-audio] [--audio mp3|m4a|wav] \
  > "$OUT/run.log" 2>&1 &!
```

Then wait with a background Bash until-loop rather than polling, e.g.
`until grep -qE '^(DONE|FAILED|NEEDS_SIGNIN)' "$OUT/status"; do sleep 15; done; cat "$OUT/status"`.

What the script does:
- probes metadata, then uses manual captions, falling back to auto captions;
- with no captions, downloads the audio and transcribes it with mlx-whisper large-v3-turbo on Apple Silicon (openai-whisper elsewhere). It gets ffmpeg from `imageio-ffmpeg` if none is installed;
- strips Whisper's silence hallucinations ("Thank you.") and the rolling repeats in auto captions;
- writes `transcript.txt` as 2-minute `[h:mm]` paragraphs, plus `meta.json`.

Timing: about 4–5 minutes of transcription per hour of audio on an M-series Mac with 8 GB, on top of the download time. Tell the user the expected wait, and if they ask for progress, report the download % or the last timestamp in `run.log`.

Use `--force-audio` when the auto captions are poor (music, heavy accents, wrong language). Use `--lang auto` for non-English videos.

**Audio extraction:** pass `--audio mp3` (or `m4a`/`wav`) whenever the user wants the audio itself: "give me the mp3", "extract the audio", a podcast version, or offline listening. The file is saved as `<title>.<format>` in `$OUT`, and its path is recorded as `audio_file` in `meta.json`. Captions are still used for the transcript when available, so asking for audio doesn't force a slow transcription. If the user only wants the audio and no summary, stop after this step and report the file.

## 3. Read everything, then summarize

Read the whole `transcript.txt`; the user usually wants every detail. Above ~60k words, read it in ordered chunks and take notes per chunk before writing.

Write `$OUT/summary.md` in your own words: a summary, not a transcript. Short quotes are fine; long verbatim passages are not. Default structure (adapt the sections to the video):

```markdown
# <Video title>

| | |
|---|---|
| Video | <title> |
| Channel | <channel> |
| Link | <url> |
| Length | <duration> |
| Speaker(s) | <only names actually stated in the video> |
| Transcript | <manual captions / auto captions / local Whisper transcription> |

## 1. At a glance
- 5-8 bullets: what the video covers and the main conclusions

## Timeline
| Time | Topic |
|---|---|
| 0:00 | ... |

## 2. <Section per chapter/topic, in video order>
### <Sub-topic>
- every concrete fact, number, name, definition, example, step, warning and recommendation
- demos and walkthroughs as numbered steps; comparisons as tables

## Key facts / takeaways
| Item | Value |

## Notes on this summary
> How the transcript was produced; misheard terms you corrected; statements the speaker got wrong (with the correction); anything inaudible or uncertain.
```

Why this shape: the timeline lets the reader jump into the video; the tables collect the facts people search for later; the notes section keeps you honest about transcription errors. Speech-to-text mangles product names and jargon, so fix them from context and list the fixes. Verify facts the speaker misstates rather than repeating them.

Keep the body sourced: everything above the Notes section should come from the transcript or `meta.json`. Readers treat the document as a record of *what the video says*, so things you happen to know about the video (who the speaker really is, where it was filmed, its history) don't belong in the body, even when you're confident. If such context genuinely helps, put it in Notes and label it "outside the video". Never assign names or pronouns the video doesn't give. If the video description is unrelated to the content (re-used or spam descriptions are common), ignore it and say so in Notes.

Size the document to the video. Use `<!-- pagebreak -->` only to start a new major part of a long document (e.g. each chapter of a multi-hour stream), never after the cover table. A 2-minute clip should fit on one or two pages.

## 4. Render and check the PDF

```bash
uv run ~/.claude/skills/youtube-summary/scripts/md_to_pdf.py "$OUT/summary.md" "$OUT/<Title>.pdf"
```

Render page 1 and one dense page to PNG, and look at them before you report:
`uvx --with pypdfium2 --with pillow python -c "..."`.
Then give the user:
- the PDF's absolute path and page count;
- a 3-5 line overview;
- any caveats: auto-generated transcript, sections that were inaudible.

The audio file can be large. Mention it and let the user decide whether to delete it.

## Troubleshooting

- `Sign in to confirm you're not a bot` / HTTP 403 on a public video: wait and retry. If it persists, it's an IP or rate-limit issue. Don't loop.
- yt-dlp JS-runtime warnings: the script passes `--js-runtimes node` when Deno is absent. Node 22+ is needed.
- No transcript words, or a transcript full of junk: check the language (`--lang auto`), or rerun with `--force-audio`.
