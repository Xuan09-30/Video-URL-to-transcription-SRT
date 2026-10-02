# YouTube to SRT Transcriber

A small web app that runs on your own computer. Paste a YouTube link and it gives you a subtitle file (`.srt`) named after the video title.

- If the video has subtitles uploaded by the creator, it downloads those (instant).
- Otherwise it downloads the audio and transcribes it with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (runs locally, no API key, no cost).

---

## 1. What you need (install once)

| Tool | Why | Windows install |
|---|---|---|
| Python 3.11 | runs the app | `winget install Python.Python.3.11` |
| FFmpeg | audio handling | `winget install Gyan.FFmpeg` |
| Deno | lets yt-dlp solve YouTube's JavaScript challenge | `winget install DenoLand.Deno` |

Open **PowerShell**, run the three commands above, then **close and reopen the terminal** so the new programs are found.

Check everything is installed:

```powershell
python --version
ffmpeg -version
deno --version
```

All three should print a version number. If one says "not recognized", restart the terminal or your PC and try again.

**Mac / Linux:**

```bash
# Mac (Homebrew)
brew install python@3.11 ffmpeg deno

# Ubuntu / Debian
sudo apt install python3 python3-venv ffmpeg
curl -fsSL https://deno.land/install.sh | sh
```

---

## 2. Get the project

Either:

- **Git:** `git clone <your-repo-link>` then `cd` into the folder, or
- **ZIP:** download the ZIP from GitHub (green **Code** button, then **Download ZIP**) and extract it.

The folder should contain:

```
app.py
requirements.txt
run.bat
README.md
```

---

## 3. Run it

### Windows (easiest)

Double-click **`run.bat`**.

The first run creates a virtual environment, installs everything, and downloads the Whisper model (about 150 MB), so it takes a few minutes. Later runs start quickly.

When you see this in the window:

```
Whisper model loaded. Server ready.
```

open **http://127.0.0.1:8000** in your browser.

### Manual (Windows PowerShell)

```powershell
cd path\to\the\project
python -m venv venv
venv\Scripts\activate
python -m pip install -U -r requirements.txt
python -m pip install -U --pre "yt-dlp[default]"
python -m uvicorn app:app
```

### Manual (Mac / Linux)

```bash
cd path/to/the/project
python3 -m venv venv
source venv/bin/activate
python -m pip install -U -r requirements.txt
python -m pip install -U --pre "yt-dlp[default]"
python -m uvicorn app:app
```

To stop the server, press **Ctrl+C** in the terminal.

---

## 4. How to use it

1. Open **http://127.0.0.1:8000**.
2. Paste a YouTube link and click **Generate SRT**.
3. Wait. The button changes to "Working... Please wait".
   - Videos with creator subtitles finish in seconds.
   - Others depend on video length and your computer. A 10 minute video is usually a few minutes on a normal CPU.
4. Your browser downloads `<video title>.srt`.

Watch the terminal while it works. It prints each step (reading info, downloading, transcribing, progress) and any errors.

**Limits:**
- Videos longer than 30 minutes are rejected (change `MAX_MINUTES`).
- Only one video should be processed at a time on a slow computer.

---

## 5. Settings

Open `app.py` and edit the block near the top:

```python
WHISPER_MODEL = "base"    # "tiny" = fastest, "small" = more accurate but slower
USE_YT_SUBS = True        # use the video's uploaded subtitles when available
USE_COOKIES = False       # only set True if you get a "confirm you're not a bot" error
BROWSER = "firefox"       # browser to read cookies from (firefox is the most reliable)
MAX_MINUTES = 30          # reject longer videos
OUTPUT_EXT = "srt"        # use "txt" if you want a .txt extension
```

Tips:
- **Faster:** use `"tiny"`. For English-only videos, `"base.en"` is faster and more accurate than `"base"`.
- **More accurate:** use `"small"`. It is slower and uses more RAM.
- **Nvidia GPU:** it is used automatically if CUDA is set up, and is often 10x faster. You can then change `compute_type="int8"` to `"float16"` in the `WhisperModel(...)` call.
- If you save the file as `.txt`, video players will no longer treat it as subtitles. Keep `.srt` for that.

---

## 6. Updating

YouTube changes often and old yt-dlp versions stop working. If downloads suddenly fail, update:

```powershell
venv\Scripts\activate
python -m pip install -U --pre "yt-dlp[default]"
```

`run.bat` already does this every time it starts.

---

## 7. Troubleshooting

### I see `{"detail":"Not Found"}`
You opened a wrong address. Go to **http://127.0.0.1:8000** (just the root, no extra path).

### `HTTP Error 403: Forbidden`
1. Update yt-dlp (section 6) and restart the app.
2. Make sure Deno works: `deno --version`.
3. Test outside the app: `python -m yt_dlp -v -x "<the video url>"`. If that also fails, it is a yt-dlp or YouTube issue, not the app.
4. Try turning cookies on (see below).

### "Sign in to confirm you're not a bot"
Set `USE_COOKIES = True` and `BROWSER = "firefox"` in `app.py`, and make sure you are logged in to YouTube in Firefox. Or test it first:

```powershell
python -m yt_dlp -v -x --cookies-from-browser firefox "<the video url>"
```

### "Could not copy Chrome cookie database" (Edge or Chrome)
Edge and Chrome lock and encrypt their cookies, so other programs often cannot read them. Use Firefox instead, or leave cookies off. Most public videos do not need cookies.

### "The page needs to be reloaded"
yt-dlp cannot solve YouTube's challenge. Install Deno, update yt-dlp, and restart the terminal.

### `ffmpeg` / `ffprobe` not found
Install FFmpeg (section 1) and restart the terminal. Check with `ffmpeg -version`.

### `deno` not found
Install Deno (section 1) and restart the terminal. Check with `deno --version`.

### It is very slow
- Use `WHISPER_MODEL = "tiny"`.
- Try shorter videos.
- Close other heavy programs.
- Videos that have creator subtitles skip transcription completely and are instant.

### Auto-generated captions are not used
Only subtitles uploaded by the creator are used directly. Videos with only YouTube's auto captions are transcribed with Whisper, because auto captions come out duplicated and messy as SRT.

### The model download is stuck or fails on first run
It needs an internet connection to download the Whisper model once (about 150 MB for `base`). Run it again, and if it still fails check your connection or firewall.

### Windows Firewall popup
Allow Python on private networks if you want other devices on your Wi-Fi to reach it (see below). It is not needed if you only use your own PC.

---

## 8. Using it from another device on the same Wi-Fi (optional)

```powershell
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Find your PC's IPv4 address with `ipconfig`, then other devices open `http://YOUR_IP:8000`. Only do this on a network you trust.

---

## 9. Privacy and safety

- Everything runs on your own computer. No videos or transcripts are sent to any third party, apart from downloading the video from YouTube.
- **Never share `cookies.txt`** or your browser cookies. They are your logged-in YouTube session.
- Temporary files are deleted automatically after each download.

## 10. Legal note

Only transcribe videos you have the right to use. Downloading content from YouTube may go against YouTube's Terms of Service, and subtitles or transcripts of someone else's video may be covered by copyright. This tool is meant for personal use such as study notes and accessibility.

---

## Project files

| File | What it does |
|---|---|
| `app.py` | the web app (download, transcribe, return the `.srt`) |
| `requirements.txt` | Python packages |
| `run.bat` | one-click setup and start for Windows |
| `.gitignore` | keeps `venv/`, cookies and generated files out of Git |
