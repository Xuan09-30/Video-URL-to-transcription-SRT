import os
import re
import sys
import glob
import time
import uuid
import shutil
import tempfile
import traceback

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from starlette.background import BackgroundTask
import yt_dlp
from yt_dlp.utils import sanitize_filename
from faster_whisper import WhisperModel

try:
    from faster_whisper import BatchedInferencePipeline  # needs faster-whisper >= 1.1
except ImportError:
    BatchedInferencePipeline = None

app = FastAPI()

# ---------- Settings ----------
WHISPER_MODEL = "base"    # "tiny" = fastest, "base.en" = faster + better for English-only videos
USE_YT_SUBS = True        # use the video's uploaded subtitles when available (instant)
USE_COOKIES = False       # set True only if you hit the "confirm you're not a bot" error
BROWSER = "firefox"       # firefox is the most reliable for cookies
MAX_MINUTES = 30
OUTPUT_EXT = "srt"        # change to "txt" if you really want .txt
YTDLP_VERBOSE = True      # prints the same output as `yt-dlp -v` in this terminal

# Tried in order until one works. The first one = same as the CLI command that worked for you.
AUDIO_ATTEMPTS = [
    {"format": "bestaudio/best"},
    {"format": "bestaudio/best", "extractor_args": {"youtube": {"player_client": ["tv", "web_safari"]}}},
    {"format": "bestaudio/best", "extractor_args": {"youtube": {"player_client": ["mweb"]}}},
    {"format": "bestaudio/best", "extractor_args": {"youtube": {"player_client": ["android_vr"]}}},
]
# ------------------------------

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def clean(text):
    """Remove terminal color codes so error messages are readable in the browser."""
    return ANSI_RE.sub("", str(text))


def log(rid, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{rid}] {msg}", flush=True)


class YDLLogger:
    """Forwards yt-dlp's output to our terminal, tagged with the request id."""

    def __init__(self, rid, tag):
        self.rid, self.tag = rid, tag

    def _p(self, level, msg):
        msg = clean(msg)
        if len(msg) > 300:
            msg = msg[:300] + " ...[cut]"   # the signed googlevideo URLs are huge
        log(self.rid, f"  yt-dlp[{self.tag}] {level}: {msg}")

    def debug(self, msg):
        self._p("", msg)

    def info(self, msg):
        self._p("", msg)

    def warning(self, msg):
        self._p("WARNING", msg)

    def error(self, msg):
        self._p("ERROR", msg)


# ---------- Startup banner ----------
print("=" * 70, flush=True)
print("NEW CODE LOADED", flush=True)
print("app file      :", os.path.abspath(__file__), flush=True)
print("python        :", sys.executable, sys.version.split()[0], flush=True)
print("yt-dlp        :", yt_dlp.version.__version__, flush=True)
print("deno          :", shutil.which("deno") or "NOT FOUND ON PATH", flush=True)
print("ffmpeg        :", shutil.which("ffmpeg") or "NOT FOUND ON PATH", flush=True)
print("whisper model :", WHISPER_MODEL, "| batched:", bool(BatchedInferencePipeline), flush=True)
print("cookies       :", f"ON ({BROWSER})" if USE_COOKIES else "OFF", flush=True)
print("yt subs       :", USE_YT_SUBS, "| max minutes:", MAX_MINUTES, flush=True)
print("=" * 70, flush=True)

model = WhisperModel(
    WHISPER_MODEL,
    device="auto",
    compute_type="int8",
    cpu_threads=os.cpu_count() or 4,
)
batched_model = BatchedInferencePipeline(model=model) if BatchedInferencePipeline else None
print("Whisper model loaded. Server ready.", flush=True)


def format_timestamp(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def pick_sub_lang(meta):
    """Pick an uploaded (manual) subtitle language, or None if there isn't one."""
    subs = {k: v for k, v in (meta.get("subtitles") or {}).items() if k != "live_chat"}
    if not subs:
        return None
    spoken = (meta.get("language") or "").split("-")[0]
    for k in subs:
        if spoken and k.split("-")[0] == spoken:
            return k
    for k in subs:
        if k.startswith("en"):
            return k
    return next(iter(subs))


def fetch(rid, url, base, use_cookies):
    """Returns (kind, path, title). kind is 'srt' (YouTube subs) or 'audio'."""
    common = {
        "outtmpl": f"{base}.%(ext)s",
        "verbose": YTDLP_VERBOSE,
        "quiet": not YTDLP_VERBOSE,
    }
    if use_cookies:
        common["cookiesfrombrowser"] = (BROWSER,)
        log(rid, f"Using cookies from {BROWSER}")

    # Step A: metadata only
    log(rid, "STEP 1/3: reading video info (no download yet)")
    t0 = time.time()
    with yt_dlp.YoutubeDL({**common, "logger": YDLLogger(rid, "info")}) as ydl:
        meta = ydl.extract_info(url, download=False)
    title = meta.get("title") or "transcript"
    duration = meta.get("duration") or 0
    log(rid, f"Got info in {time.time() - t0:.1f}s | title={title!r} | duration={duration}s")
    log(rid, f"Uploaded subtitle languages: {list((meta.get('subtitles') or {}).keys())}")
    log(rid, f"Auto-caption languages: {len(meta.get('automatic_captions') or {})} available (not used)")

    if duration > MAX_MINUTES * 60:
        raise HTTPException(status_code=400, detail=f"Video is longer than {MAX_MINUTES} minutes.")

    # Step B: fast path with creator-uploaded subtitles
    lang = pick_sub_lang(meta) if USE_YT_SUBS else None
    if lang:
        log(rid, f"STEP 2/3: trying uploaded subtitles (lang={lang})")
        sub_opts = {
            **common,
            "logger": YDLLogger(rid, "subs"),
            "skip_download": True,
            "writesubtitles": True,
            "subtitleslangs": [lang],
            "subtitlesformat": "srt/vtt",
            "postprocessors": [{"key": "FFmpegSubtitlesConvertor", "format": "srt"}],
        }
        try:
            with yt_dlp.YoutubeDL(sub_opts) as ydl:
                ydl.process_ie_result(meta, download=True)
            files = glob.glob(glob.escape(base) + "*.srt")
            log(rid, f"Subtitle files found: {files}")
            if files:
                return "srt", files[0], title
        except yt_dlp.utils.DownloadError as e:
            log(rid, f"Subtitle download failed, falling back to Whisper: {clean(e)}")
    else:
        log(rid, "STEP 2/3: no uploaded subtitles (or disabled) -> will use Whisper")

    # Step C: audio download, with fallbacks
    log(rid, f"STEP 3/3: downloading audio ({len(AUDIO_ATTEMPTS)} attempts possible)")
    last_err = None
    for n, extra in enumerate(AUDIO_ATTEMPTS, start=1):
        log(rid, f"--- Audio attempt {n}/{len(AUDIO_ATTEMPTS)}: {extra}")
        t0 = time.time()
        opts = {**common, **extra, "retries": 3, "logger": YDLLogger(rid, f"audio{n}")}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            path = info["requested_downloads"][0]["filepath"]
            size_mb = os.path.getsize(path) / 1024 / 1024
            log(rid, f"Attempt {n} OK in {time.time() - t0:.1f}s -> {path} ({size_mb:.1f} MB)")
            return "audio", path, title
        except yt_dlp.utils.DownloadError as e:
            last_err = e
            log(rid, f"Attempt {n} FAILED after {time.time() - t0:.1f}s: {clean(e)}")
    log(rid, "ALL audio attempts failed")
    raise last_err


def transcribe_to_srt(rid, audio_path, srt_path):
    log(rid, f"Transcribing {audio_path} ({'batched' if batched_model else 'normal'} mode)")
    t0 = time.time()
    if batched_model:
        segments, info = batched_model.transcribe(audio_path, batch_size=8, beam_size=1)
    else:
        segments, info = model.transcribe(
            audio_path, vad_filter=True, beam_size=1, condition_on_previous_text=False
        )
    log(rid, f"Detected language: {info.language} (p={info.language_probability:.2f}) | "
             f"audio length: {info.duration:.0f}s")

    count = 0
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(f"{format_timestamp(seg.start)} --> {format_timestamp(seg.end)}\n")
            f.write(f"{seg.text.strip()}\n\n")
            count = i
            if i % 20 == 0:
                log(rid, f"  ...{i} segments done, at {seg.end:.0f}s of {info.duration:.0f}s")
    log(rid, f"Transcription finished: {count} segments in {time.time() - t0:.1f}s")


@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>YouTube to SRT</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-100 flex items-center justify-center h-screen">
        <div class="bg-white p-8 rounded-lg shadow-md w-full max-w-md">
            <h1 class="text-2xl font-bold mb-4 text-center">YouTube Transcriber</h1>
            <form action="/generate" method="post" class="flex flex-col gap-4">
                <input type="url" name="url" placeholder="Paste YouTube Link Here" required
                       class="border p-2 rounded focus:outline-none focus:ring-2 focus:ring-blue-500">
                <button type="submit" onclick="this.innerText='Working... Please wait'"
                        class="bg-blue-600 text-white p-2 rounded hover:bg-blue-700 transition">
                    Generate SRT
                </button>
            </form>
        </div>
    </body>
    </html>
    """


# Plain `def` so FastAPI runs it in a threadpool and the server isn't blocked
@app.post("/generate")
def generate_srt(url: str = Form(...)):
    rid = uuid.uuid4().hex[:6]
    t_start = time.time()
    log(rid, "=" * 50)
    log(rid, f"NEW REQUEST: {url}")

    tmp_dir = tempfile.mkdtemp()
    base = os.path.join(tmp_dir, uuid.uuid4().hex)
    out_path = f"{base}.out.srt"
    log(rid, f"Temp folder: {tmp_dir}")

    def cleanup():
        if os.path.isdir(tmp_dir):
            left = os.listdir(tmp_dir)
            for leftover in left:
                os.remove(os.path.join(tmp_dir, leftover))
            os.rmdir(tmp_dir)
            log(rid, f"Cleaned up temp folder ({len(left)} files removed)")

    # 1. Get subtitles or audio (if cookies are on and fail, retry without them)
    try:
        try:
            kind, path, title = fetch(rid, url, base, USE_COOKIES)
        except yt_dlp.utils.DownloadError as e:
            if not USE_COOKIES:
                raise
            log(rid, f"Download with {BROWSER} cookies failed, retrying without: {clean(e)}")
            kind, path, title = fetch(rid, url, base, False)
    except yt_dlp.utils.DownloadError as e:
        log(rid, f"FINAL FAILURE (download): {clean(e)}")
        cleanup()
        raise HTTPException(status_code=400, detail=f"Download failed: {clean(e)}")
    except HTTPException as e:
        log(rid, f"Rejected: {e.detail}")
        cleanup()
        raise
    except Exception as e:
        log(rid, f"UNEXPECTED ERROR while fetching: {e!r}")
        traceback.print_exc()
        cleanup()
        raise HTTPException(status_code=500, detail=f"Unexpected error: {clean(e)}")

    log(rid, f"Fetch done: kind={kind}, path={path}")
    log(rid, f"Files in temp folder: {os.listdir(tmp_dir)}")

    # 2. Transcribe only if YouTube had no uploaded subtitles
    if kind == "srt":
        out_path = path
        log(rid, "Using YouTube's own subtitles, skipping Whisper")
    else:
        try:
            transcribe_to_srt(rid, path, out_path)
        except Exception as e:
            log(rid, f"TRANSCRIPTION ERROR: {e!r}")
            traceback.print_exc()
            cleanup()
            raise HTTPException(status_code=500, detail=f"Transcription failed: {clean(e)}")

    # 3. Send it back named after the video title, then clean up
    log(rid, f"DONE in {time.time() - t_start:.1f}s -> sending {sanitize_filename(title)}.{OUTPUT_EXT}")
    return FileResponse(
        out_path,
        media_type="text/plain",
        filename=f"{sanitize_filename(title)}.{OUTPUT_EXT}",
        background=BackgroundTask(cleanup),
    )