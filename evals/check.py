"""Grade every run in an iteration folder; writes grading.json per run.

Usage: uvx --with pypdf python check.py iteration-1
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from pypdf import PdfReader

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")


def pdf_text(out):
    pdfs = sorted(out.rglob("*.pdf"))
    if not pdfs:
        return None, ""
    return pdfs[0], " ".join(p.extract_text() or "" for p in PdfReader(pdfs[0]).pages)


def meta(out):
    m = sorted(out.rglob("meta.json"))
    return json.loads(m[0].read_text()) if m else {}


def mp3_seconds(out):
    mp3s = sorted(out.rglob("*.mp3"))
    if not mp3s:
        return None, None
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(mp3s[0])], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    secs = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None
    return mp3s[0], secs


def page1_ok(pdf):
    if pdf is None:
        return False, "no pdf"
    pages = PdfReader(pdf).pages
    n = len((pages[0].extract_text() or "").strip())
    return len(pages) == 1 or n >= 500, f"{len(pages)} pages, page 1 has {n} chars of text"


def body_sourced(out):
    md = "".join(p.read_text() for p in out.rglob("summary.md"))
    body = re.split(r"^#+ .*notes", md, flags=re.I | re.M)[0]
    hits = [w for w in ("Karim", "San Diego", "first video", "first YouTube") if w.lower() in body.lower()]
    return not hits, f"outside facts in body: {hits}" if hits else "none above the Notes section"


def check(name, out):
    pdf, text = pdf_text(out)
    m = meta(out)
    src = m.get("transcript_source", "")
    tx = "".join(p.read_text() for p in out.rglob("transcript.txt"))
    res = [("A PDF was produced", pdf is not None, str(pdf) if pdf else "no .pdf in outputs"),
           ("Page 1 is not mostly empty (>=500 chars, or a 1-page PDF)", *page1_ok(pdf))]
    if "zoo" in name:
        res.append(("No outside facts about the video above the Notes section", *body_sourced(out)))
    if "webinar" in name:
        res.append(("meta.json records the local file's duration", bool(m.get("duration")),
                    f"duration={m.get('duration')!r}, duration_string={m.get('duration_string')!r}"))
    if "zoo" in name:
        res.append(("The PDF names the video ('Me at the zoo') and channel (jawed)",
                    "Me at the zoo" in text and "jawed" in text.lower(),
                    f"title={'Me at the zoo' in text}, channel={'jawed' in text.lower()}"))
        res.append(("The transcript came from captions (no slow Whisper run)",
                    "captions" in src, f"transcript_source={src!r}"))
    if "webinar" in name:
        res.append(("The local file was transcribed with Whisper", "whisper" in src,
                    f"transcript_source={src!r}"))
        n = len(re.findall(r"(?<![\w ])Thank you\.", tx))
        res.append(("No phantom standalone 'Thank you.' lines in the transcript", n == 0,
                    f"{n} standalone 'Thank you.' found"))
        res.append(("The notes capture the closing remarks (thanks to the team / see you tomorrow)",
                    bool(re.search(r"tomorrow|support team|team", text, re.I)),
                    "matched" if re.search(r"tomorrow|support team|team", text, re.I) else "not found"))
    if "mp3" in name:
        mp3, secs = mp3_seconds(out)
        res.append(("A playable mp3 of the full audio (~19 s) was produced",
                    bool(secs and 17 <= secs <= 21), f"{mp3}: {secs}s" if mp3 else "no .mp3"))
    return [{"text": t, "passed": bool(p), "evidence": e} for t, p, e in res]


for run in sorted(Path(sys.argv[1]).glob("eval-*/*/run-*/")):
    exp = check(run.parent.parent.name, run / "outputs")
    passed = sum(e["passed"] for e in exp)
    (run / "grading.json").write_text(json.dumps({
        "expectations": exp,
        "summary": {"passed": passed, "failed": len(exp) - passed, "total": len(exp),
                    "pass_rate": round(passed / len(exp), 2)},
    }, indent=2))
    print(f"{run.parent.parent.name}/{run.parent.name}: {passed}/{len(exp)}")
