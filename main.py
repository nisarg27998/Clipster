import os
import sys
import re
import json
import time
import queue
import threading
import tempfile
import atexit
import subprocess
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

_HISTORY_RW_LOCK = threading.RLock()

# --------------------------------------------
# Branding / Config
# --------------------------------------------
APP_NAME = "Clipster"
APP_VERSION = "1.2.8"
ACCENT_COLOR = "#0078D7"
SECONDARY_COLOR = "#00B7C2"
SPLASH_TEXT = "Fetch. Download. Enjoy."

GITHUB_REPO = "nisarg27998/Clipster"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "Assets"
APP_ICON_PATH = ASSETS_DIR / "app_icon.ico"
WINDOWS_DOWNLOADS_DIR = str(Path.home() / "Downloads")
DOWNLOADS_DIR = BASE_DIR / "downloads"
TEMP_DIR = BASE_DIR / "temp"
HISTORY_FILE = BASE_DIR / "history.json"
SETTINGS_FILE = BASE_DIR / "settings.json"

YT_DLP_EXE = ASSETS_DIR / "yt-dlp.exe"
FFMPEG_EXE = ASSETS_DIR / "ffmpeg.exe"
FFPROBE_EXE = ASSETS_DIR / "ffprobe.exe"
FFPLAY_EXE = ASSETS_DIR / "ffplay.exe"

ALLOWED_FORMATS = ["mp4", "mkv", "webm", "m4a"]

YOUTUBE_URL_RE = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+", re.IGNORECASE)
YT_DLP_PROGRESS_RE = re.compile(r"\[download\]\s+([\d\.]+)%")
YT_DLP_SPEED_RE = re.compile(r"at\s+([0-9\.]+\w+/s)")
YT_DLP_ETA_RE = re.compile(r"ETA\s+([0-9:]+)")

LOG_FILE = BASE_DIR / "clipster.log"

# --------------------------------------------
# Update check (GitHub latest release)
# --------------------------------------------\

def get_pil_image():
    global Image
    if 'Image' not in globals():
        from PIL import Image as PILImage
        Image = PILImage
    return Image


def run_subprocess_safe(cmd, timeout=300, cwd=None, capture_output=True):
    """
    Run subprocess in a consistent way, capture stdout/stderr, return dict:
    { 'returncode': int, 'stdout': str, 'stderr': str, 'timed_out': bool }
    """
    try:
        popen_kwargs = {"stdout": subprocess.PIPE if capture_output else None,
                        "stderr": subprocess.PIPE if capture_output else None,
                        "text": True}
        if _is_windows():
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            popen_kwargs["startupinfo"] = si
            popen_kwargs["creationflags"] = 0x08000000
        proc = subprocess.Popen(cmd, cwd=cwd, **popen_kwargs)
        try:
            out, err = proc.communicate(timeout=timeout)
            return {"returncode": proc.returncode, "stdout": out or "", "stderr": err or "", "timed_out": False}
        except subprocess.TimeoutExpired:
            try:
                proc.terminate()
                time.sleep(0.2)
                proc.kill()
            except Exception:
                pass
            return {"returncode": None, "stdout": "", "stderr": "Timed out", "timed_out": True}
    except Exception as e:
        return {"returncode": None, "stdout": "", "stderr": str(e), "timed_out": False}
        

# --------------------------------------------
# Helpers: Sanitize filenames
# --------------------------------------------

_SAFE_FILENAME_RE = re.compile(r'[^A-Za-z0-9 ._\-()]')







def safe_filename(name: str, max_len=200, default="file"):
    if not name:
        return default
    name = str(name)
    # replace illegal characters
    cleaned = _SAFE_FILENAME_RE.sub("_", name)
    # collapse repeated underscores
    cleaned = re.sub(r'_{2,}', '_', cleaned).strip(" _")
    if not cleaned:
        return default
    # trim length but preserve extension if present
    if len(cleaned) > max_len:
        base, ext = os.path.splitext(cleaned)
        keep = max_len - len(ext)
        cleaned = base[:keep] + ext
    return cleaned


# --------------------------------------------
# Helpers: log & filesystem checks
# --------------------------------------------
def log_message(msg: str):
    """Log a message to the log file with timestamp."""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{now_str()}] {msg}\n")
    except Exception:
        pass

def log_debug(msg):
    try:
        settings = None
        # If app exists on module level, try to read debug flag
        if 'app' in globals() and getattr(globals()['app'], 'settings', None):
            settings = globals()['app'].settings
        if settings and settings.get("debug_mode"):
            log_message("[DEBUG] " + msg)
    except Exception:
        log_message("[DEBUG] " + msg)


def open_log_file():
    """Open the Clipster log file in the default text editor (Windows)."""
    try:
        if not LOG_FILE.exists():
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write("Clipster Log — Created automatically.\n\n")
        os.startfile(str(LOG_FILE))
    except Exception as e:
        messagebox.showerror(APP_NAME, f"Unable to open log file:\n{e}")

def ensure_directories():
    """Ensure required directories exist."""
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

def check_executables():
    """Check for required executables in Assets/."""
    missing = []
    for exe in [YT_DLP_EXE, FFMPEG_EXE, FFPROBE_EXE, FFPLAY_EXE]:
        if not exe.exists():
            missing.append(exe.name)
    return missing

# --------------------------------------------
# Settings & History JSON
# --------------------------------------------
DEFAULT_SETTINGS = {
    "debug_mode": False,
    "default_format": "mp4",
    "theme": "dark",
    "use_smart_naming": True,

    # default to user's Windows Downloads folder (cross-platform fallback)
    "default_download_path": WINDOWS_DOWNLOADS_DIR,
    "cookies_path": "",
    "show_toasts": True,
    "thumbnail_after_fetch": True
}
# -------------------------------------------------------------------------------


def load_settings():
    """Load settings from JSON file, falling back to defaults."""
    if not SETTINGS_FILE.exists():
        # Don't save immediately - defer to first actual change
        return DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults efficiently
        return {**DEFAULT_SETTINGS, **data}
    except Exception:
        return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    try:
        ok = safe_write_json(SETTINGS_FILE, settings)
        if not ok:
            log_message("save_settings: safe_write_json returned False")
    except Exception as e:
        log_message(f"Failed to save settings: {e}")


def load_history():
    # Fix: Acquire lock even for reading to ensure we don't read partial writes
    with _HISTORY_RW_LOCK:
        data = safe_read_json(HISTORY_FILE, default=[])
        if data is None:
            return []
        return data


def append_history(entry):
    # Fix: Atomic read-modify-write cycle
    with _HISTORY_RW_LOCK:
        history = load_history() or []
        history.insert(0, entry)
        safe_write_json(HISTORY_FILE, history)


def delete_history_entry(index):
    # Fix: Atomic read-modify-write cycle
    with _HISTORY_RW_LOCK:
        history = load_history()
        if history and 0 <= index < len(history):
            history.pop(index)
            safe_write_json(HISTORY_FILE, history)

def clear_history():
    with _HISTORY_RW_LOCK:
        safe_write_json(HISTORY_FILE, [])

# --------------------------------------------
# Utility
# --------------------------------------------
def safe_path(path_like):
    """Resolve and return a safe string path."""
    return str(Path(path_like).resolve())

def windows_quote(path):
    """Quote path for Windows subprocess (placeholder, as is)."""
    return str(path)

def is_youtube_url(url):
    """Basic check if URL is a YouTube URL."""
    return bool(YOUTUBE_URL_RE.match(url.strip()))

def now_str():
    """Get current datetime as string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ---------- Atomic JSON write/read with optional file lock ----------
_FILE_LOCK_TIMEOUT = 5.0  # seconds for lock attempts

def _acquire_file_lock(lock_path, timeout=_FILE_LOCK_TIMEOUT):
    """
    Best-effort cross-process lock:
    Try to create a lock file atomically (O_CREAT|O_EXCL).
    Return a file descriptor which should be closed/unlinked by caller.
    If can't acquire within timeout, raise TimeoutError.
    """

    import errno

    start = time.monotonic()
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            # write pid for debugging
            try:
                os.write(fd, str(os.getpid()).encode("utf-8"))
            except Exception:
                pass
            return fd
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"Could not acquire lock {lock_path}")
            time.sleep(0.05)

def _release_file_lock(fd, lock_path):
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        os.unlink(lock_path)
    except Exception:
        pass




def safe_write_json(path: Path, data, *, lock_suffix=".lock"):
    """Write JSON atomically using tempfile + os.replace with optional lock."""
    path = Path(path)
    lock_path = str(path) + lock_suffix
    fd = None
    try:
        try:
            fd = _acquire_file_lock(lock_path)
        except TimeoutError:
            # fallback to in-process lock only (best-effort)
            log_message(f"safe_write_json: lock timeout for {path}, proceeding without lock")
            fd = None

        # write to temp file in same dir to ensure os.replace is atomic
        dirpath = path.parent
        dirpath.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(dirpath), delete=False) as tf:
            json.dump(data, tf, indent=2, ensure_ascii=False)
            tf.flush()
            os.fsync(tf.fileno())
            tmpname = tf.name
        os.replace(tmpname, str(path))
        return True
    except Exception as e:
        log_message(f"safe_write_json failed for {path}: {e}")
        try:
            if 'tmpname' in locals() and os.path.exists(tmpname):
                os.unlink(tmpname)
        except Exception:
            pass
        return False
    finally:
        if fd:
            try:
                _release_file_lock(fd, lock_path)
            except Exception:
                pass

def safe_read_json(path: Path, default=None, *, lock_suffix=".lock"):
    """Read JSON file; if it fails return default. We don't lock on read to avoid contention."""
    try:
        if not Path(path).exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log_message(f"safe_read_json failed for {path}: {e}")
        return default


# ------------------ Toast / notification helpers (add after now_str) ------------------
def _is_windows():
    return sys.platform.startswith("win")

def show_toast(root, message, title=None, timeout=3000, level="info", theme="dark"):
    """Non-blocking themed toast with Windows 11 styling."""
    try:
        if not getattr(root, "_toast_enabled", True):
            return
        toast = ctk.CTkToplevel(root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        # Windows 11 acrylic colors
        if theme == "light":
            bg = "#f3f3f3"
            fg = "#000000"
        else:
            bg = "#2b2b2b"
            fg = "#ffffff"
        # Frame with rounded corners (Windows 11 style)
        frame = ctk.CTkFrame(toast, fg_color=bg, corner_radius=12, border_width=1, 
                            border_color="#404040" if theme == "dark" else "#d0d0d0")
        frame.pack(fill="both", expand=True, padx=2, pady=2)
        
        title_text = title or ""
        lbl_title = ctk.CTkLabel(frame, text=title_text, anchor="w", font=ctk.CTkFont(size=12, weight="bold"))
        if title_text:
            lbl_title.pack(fill="x", padx=16, pady=(12, 0))
        lbl = ctk.CTkLabel(frame, text=message, anchor="w", font=ctk.CTkFont(size=11))
        lbl.pack(fill="both", padx=16, pady=(8, 14))
        
        try:
            x = root.winfo_x() + root.winfo_width() - 340 - 20
            y = root.winfo_y() + root.winfo_height() - 110 - 20
            toast.geometry(f"340x90+{x}+{y}")
        except Exception:
            toast.geometry("340x90+100+100")
        
        # Fade in effect
        toast.attributes("-alpha", 0.0)
        def fade_in(alpha=0.0):
            if alpha < 0.95:
                alpha += 0.1
                toast.attributes("-alpha", alpha)
                toast.after(20, lambda: fade_in(alpha))
            else:
                toast.attributes("-alpha", 0.95)
        fade_in()
        
        # Auto-destroy with fade out
        def fade_out(alpha=0.95):
            if alpha > 0:
                alpha -= 0.1
                try:
                    toast.attributes("-alpha", alpha)
                    toast.after(20, lambda: fade_out(alpha))
                except:
                    pass
            else:
                try:
                    toast.destroy()
                except:
                    pass
        toast.after(timeout, lambda: fade_out())
    except Exception:
        pass

# ------------------ Windows Native Notification ------------------

def windows_notify(title, message, open_path=None):
    try:
        if not _is_windows():
            return

        from win11toast import toast

        kwargs = {
            "title": title,
            "body": message,
            "duration": "short"
        }

        if open_path and os.path.exists(open_path):
            kwargs["on_click"] = lambda *_: os.startfile(open_path)

        _ = toast(**kwargs)

    except Exception as e:
        log_message(f"windows_notify error: {e}")




# convenience wrapper that checks settings
def _toast(app, message, title=None, timeout=3000, level="info"):
    """Thread-safe wrapper for showing toasts."""
    if not getattr(app, "settings", None):
        return
    if not app.settings.get("show_toasts", True):
        return
    
    # Fix: Ensure UI creation happens on the main thread
    if threading.current_thread() is threading.main_thread():
        try:
            show_toast(app.root, message, title=title, timeout=timeout, level=level, theme=app.settings.get("theme","dark"))
        except Exception:
            pass
    else:
        app.root.after(0, lambda: _toast(app, message, title, timeout, level))
# ---------------------------------------------------------------------------------------


# --------------------------------------------
# Metadata via yt-dlp --dump-json (blocking small call)
# --------------------------------------------
def fetch_metadata_via_yt_dlp(url, timeout=30):
    """Fetch video metadata using yt-dlp; hides console window on Windows."""
    if not YT_DLP_EXE.exists():
        raise FileNotFoundError("yt-dlp.exe not found in Assets/")
    cmd = [windows_quote(str(YT_DLP_EXE)), "--no-warnings", "--skip-download", "--dump-json", url]
    try:
        # Windows: hide window
        kwargs = {"capture_output": True, "text": True, "timeout": timeout}
        if _is_windows():
            # Use STARTUPINFO to hide
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            kwargs["startupinfo"] = si
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        proc = subprocess.run(cmd, **kwargs)
        out = proc.stdout.strip()
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip() or out
            if any(x in stderr for x in ("Sign in to confirm your age", "members-only", "This video is only available for members")):
                raise RuntimeError("This video is age-restricted or members-only and requires sign-in. Clipster cannot download it.")
            raise RuntimeError(stderr or "yt-dlp failed to fetch metadata")
        if not out:
            raise RuntimeError("No metadata returned by yt-dlp")
        # find the first JSON object in output
        first_json = None
        for line in out.splitlines():
            if line.strip().startswith("{"):
                first_json = line
                break
        if first_json is None:
            first_json = out
        return json.loads(first_json)
    except subprocess.TimeoutExpired:
        raise RuntimeError("yt-dlp timed out while fetching metadata")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse yt-dlp output as JSON: {e}")
# ---------------------------------------------------------------------------------------


# --------------------------------------------
# Download process wrapper (yt-dlp)
# --------------------------------------------
class DownloadProcess:
    """Manages a single yt-dlp download process."""
    def __init__(self):
        self.proc = None
        self._lock = threading.Lock()
        self.last_args = None
        self.paused = False


    def pause(self):
        with self._lock:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                    self.paused = True
                except Exception:
                    pass


    def resume(self):
        if self.paused and self.last_args:
            self.paused = False
            self.start_download(*self.last_args)


    def shutdown(self):
        with self._lock:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                    time.sleep(0.2)
                    if self.proc.poll() is None:
                        self.proc.kill()
                except Exception:
                    pass
            self.proc = None


    def start_download(self, url, outdir, filename_template, format_selector, cookies_path=None, progress_callback=None, finished_callback=None, error_callback=None):
        """Start a download thread."""
        self.last_args = (
            url,
            outdir,
            filename_template,
            format_selector,
            cookies_path,
            progress_callback,
            finished_callback,
            error_callback,
        )
        self.paused = False
        thread = threading.Thread(target=self._run_download, args=(url, outdir, filename_template, format_selector, cookies_path, progress_callback, finished_callback, error_callback), daemon=True)
        thread.start()
        return thread

    def _run_download(self, url, outdir, filename_template, format_selector, cookies_path, progress_callback, finished_callback, error_callback):
        """Internal method to run yt-dlp subprocess (hidden window on Windows)."""
        if not YT_DLP_EXE.exists():
            if error_callback: error_callback("yt-dlp.exe not found in Assets/")
            return
        outtmpl = os.path.join(outdir, filename_template)
        cmd = [windows_quote(str(YT_DLP_EXE)), "--no-warnings", "--newline"]
        if cookies_path:
            cmd += ["--cookies", windows_quote(cookies_path)]
        cmd += ["-o", outtmpl, "-f", format_selector, url]

        try:
            popen_kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True, "bufsize": 1, "universal_newlines": True}
            if _is_windows():
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = subprocess.SW_HIDE
                popen_kwargs["startupinfo"] = si
                popen_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            with subprocess.Popen(cmd, **popen_kwargs) as p:
                with self._lock:
                    self.proc = p
                output_path = None
                for raw_line in p.stdout:
                    if raw_line is None:
                        continue
                    line = raw_line.strip()
                    # age-restricted detection
                    if any(x in line for x in ("Sign in to confirm your age", "This video is only available for members", "This video is private")):
                        if error_callback:
                            error_callback("Age-restricted or members-only content detected. Clipster cannot download without authentication.")
                        try:
                            p.terminate()
                        except Exception:
                            pass
                        return
                    # percent parsing
                    match = YT_DLP_PROGRESS_RE.search(line)
                    percent = None
                    speed = None
                    eta = None
                    if match:
                        try:
                            percent = float(match.group(1))
                        except:
                            percent = None
                    sp = YT_DLP_SPEED_RE.search(line)
                    if sp:
                        speed = sp.group(1)
                    etam = YT_DLP_ETA_RE.search(line)
                    if etam:
                        eta = etam.group(1)
                    if line.startswith("Destination:"):
                        # yt-dlp prints Destination: path
                        output_path = line.partition("Destination:")[2].strip()
                    if progress_callback:
                        progress_callback(percent, speed, eta, line)
                ret = p.wait()
                with self._lock:
                    self.proc = None
                if ret == 0:
                    if finished_callback:
                        finished_callback(output_path)
                else:
                    if error_callback:
                        error_callback(f"yt-dlp exited with code {ret}")

        except Exception as e:
            if error_callback:
                error_callback(str(e))
        finally:
            with self._lock:
                self.proc = None

    def cancel(self):
        """Cancel the running download process."""
        with self._lock:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                    time.sleep(0.2)
                    if self.proc.poll() is None:
                        self.proc.kill()
                except Exception:
                    pass

# --------------------------------------------
# Thumbnail download & embed (ffmpeg)
# --------------------------------------------
def download_thumbnail(url, target_filename=None, timeout=20):
    import requests, shutil
    """Download thumbnail from URL to user's Downloads folder."""
    try:
        downloads_path = str(Path.home() / "Downloads")
        os.makedirs(downloads_path, exist_ok=True)
        if not target_filename:
            filename = f"clipster_thumb_{int(time.time())}.jpg"
        else:
            filename = target_filename
        target_path = os.path.join(downloads_path, filename)

        r = requests.get(url, stream=True, timeout=timeout)
        r.raise_for_status()
        with open(target_path, "wb") as f:
            shutil.copyfileobj(r.raw, f)

        return target_path  # return saved file path
    except Exception as e:
        log_message(f"download_thumbnail error: {e}")
        return None


# ------------------ New helper: get_best_thumbnail_url ------------------
def get_best_thumbnail_url(meta_or_url_or_vid):
    """
    Given meta dict, full url, or vid id - return a likely thumbnail URL.
    Tries meta['thumbnail'] first, then YouTube standard endpoints.
    """

    from urllib.parse import urlparse, parse_qs

    try:
        if isinstance(meta_or_url_or_vid, dict):
            t = meta_or_url_or_vid.get("thumbnail")
            if t:
                return t
            url = meta_or_url_or_vid.get("webpage_url") or meta_or_url_or_vid.get("url") or ""
        else:
            url = str(meta_or_url_or_vid or "")
        # attempt to extract video id
        vid = None
        if "watch?v=" in url or "youtu.be" in url or "youtube" in url:
            vid = None
            try:
                parsed = urlparse(url)
                if parsed.netloc and "youtu.be" in parsed.netloc:
                    vid = parsed.path.lstrip("/")
                else:
                    qs = parse_qs(parsed.query)
                    if "v" in qs:
                        vid = qs["v"][0]
            except Exception:
                vid = None
        if not vid:
            # maybe passed a raw id
            m = re.search(r"([A-Za-z0-9_-]{11})", url)
            if m:
                vid = m.group(1)
        if vid:
            # try high-quality variants in order
            candidates = [
                f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
                f"https://i.ytimg.com/vi/{vid}/sddefault.jpg",
                f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
            ]
            return candidates[0]  # caller will attempt download & fallback to others if missing
        return None
    except Exception:
        return None
# ---------------------------------------------------------------------------------------


def embed_thumbnail_with_ffmpeg(video_path, thumb_path):
    """Embed thumbnail into video using ffmpeg in a safe atomic way."""


    if not FFMPEG_EXE.exists():
        return False
    video_path = Path(video_path)
    thumb_path = Path(thumb_path)
    if not video_path.exists() or not thumb_path.exists():
        return False
    try:
        with tempfile.NamedTemporaryFile(prefix="clipster_ffmpeg_", suffix=video_path.suffix, delete=False) as tmpf:
            out_tmp = Path(tmpf.name)
        cmd = [
            windows_quote(str(FFMPEG_EXE)),
            "-y",
            "-i", str(video_path),
            "-i", str(thumb_path),
            "-map", "0",
            "-map", "1",
            "-c", "copy",
            "-disposition:v:1", "attached_pic",
            str(out_tmp)
        ]
        popen_kwargs = {"capture_output": True, "text": True}
        if _is_windows():
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            popen_kwargs["startupinfo"] = si
            popen_kwargs["creationflags"] = 0x08000000
        proc = subprocess.run(cmd, **popen_kwargs)
        if proc.returncode != 0:
            try:
                out_tmp.unlink(missing_ok=True)
            except Exception:
                pass
            log_message(f"FFmpeg embed failed: {proc.stderr}")
            return False
        # atomic replace
        try:
            backup = video_path.with_suffix(video_path.suffix + ".bak")
            video_path.replace(backup)
            out_tmp.replace(video_path)
            backup.unlink(missing_ok=True)
        except Exception:
            try:
                os.replace(str(out_tmp), str(video_path))
            except Exception:
                log_message("embed_thumbnail_with_ffmpeg: atomic replace failed")
                return False
        # cleanup thumb
        try:
            thumb_path.unlink(missing_ok=True)
        except Exception:
            pass
        return True
    except Exception as e:
        log_message(f"embed_thumbnail_with_ffmpeg exception: {e}")
        return False
# ---------------------------------------------------------------------------------------


# --------------------------------------------
# Format selector helpers
# --------------------------------------------
def build_format_selector_for_format_and_res(target_format, resolution_label):
    """Build yt-dlp format selector string based on format and resolution."""
    if target_format == "mp4":
        return "bestvideo[ext=mp4][height<=?1080]+bestaudio[ext=m4a]/best"
    if target_format == "m4a":
        return "bestaudio[ext=m4a]/bestaudio"
    if target_format == "webm":
        return "bestvideo[ext=webm]+bestaudio[ext=webm]/best"
    if target_format == "mkv":
        return "bestvideo[ext=mkv]+bestaudio/best"
    return "best"

def resolution_to_height(res_label):
    """Map resolution label to height."""
    mapping = {
        "Best Available": None,
        "2160p": 2160,
        "1440p": 1440,
        "1080p": 1080,
        "720p": 720,
    }
    return mapping.get(res_label, None)

def build_batch_format_selector(target_format, max_resolution_label):
    """Build format selector for batch/playlist downloads."""
    height = resolution_to_height(max_resolution_label)
    if height:
        if target_format == "mp4":
            return f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}]"
        else:
            return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
    else:
        if target_format == "mp4":
            return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"
        return "bestvideo+bestaudio/best"

# --------------------------------------------
# GUI application (customtkinter)
# --------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class SplashScreen(ctk.CTkToplevel):
    def __init__(self, root):
        super().__init__(root)

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color="#121212")

        width, height = 420, 260
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

        container = ctk.CTkFrame(
            self,
            corner_radius=18,
            fg_color="#1a1a1a"
        )
        container.pack(expand=True, fill="both", padx=8, pady=8)

        # Logo
        try:
            Image = get_pil_image()
            logo_path = ASSETS_DIR / "clipster.png"
            if logo_path.exists():
                img = Image.open(logo_path).convert("RGBA")
                img.thumbnail((72, 72))
                self.logo_img = ctk.CTkImage(img, size=(72, 72))
                ctk.CTkLabel(container, image=self.logo_img, text="").pack(pady=(24, 10))
        except Exception:
            pass

        # App name
        ctk.CTkLabel(
            container,
            text=APP_NAME,
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack()

        # Tagline
        ctk.CTkLabel(
            container,
            text=SPLASH_TEXT,
            font=ctk.CTkFont(size=13),
            text_color="#9aa0a6"
        ).pack(pady=(2, 18))

        # Spinner
        self.progress = ctk.CTkProgressBar(
            container,
            mode="indeterminate",
            height=6,
            corner_radius=6
        )
        self.progress.pack(fill="x", padx=60)
        self.progress.start()

        # Fade-in
        self.attributes("-alpha", 0.0)
        self._fade_in()

    def _fade_in(self, alpha=0.0):
        if alpha < 1.0:
            alpha += 0.08
            self.attributes("-alpha", alpha)
            self.after(15, lambda: self._fade_in(alpha))

    # ✅ NEW: Fade-out animation
    def fade_out_and_destroy(self, alpha=1.0):
        if alpha > 0:
            alpha -= 0.08
            self.attributes("-alpha", alpha)
            self.after(15, lambda: self.fade_out_and_destroy(alpha))
        else:
            self.progress.stop()
            self.destroy()



class ClipsterApp:

    def pause_download(self):
        self.download_proc.pause()
        self.single_pause_btn.configure(text="Resume", command=self.resume_download)
        _toast(self, "Download paused.", title="Paused")

    def resume_download(self):
        self.download_proc.resume()
        self.single_pause_btn.configure(text="Pause", command=self.pause_download)
        _toast(self, "Resuming download...", title="Resume")

    def get_executor(self):
        if self._executor is None:
            import concurrent.futures
            self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=6)
        return self._executor

    def run_bg(self, func, *args):
        if getattr(self, "_executor", None):
            self.get_executor().submit(func, *args)


    """Main application class for Clipster GUI."""
    def __init__(self, root):
        import concurrent.futures
        self.root = root

        # enable toasts on root
        try:
            self.root._toast_enabled = True
        except Exception:
            pass

        self.root.title(f"{APP_NAME} - {SPLASH_TEXT}")
        self.root.geometry("1000x700")
        self.root.minsize(900, 600)

        # Hide window initially to prevent flashing during setup
        #self.root.withdraw()

        ensure_directories()
        # Defer executable checks to after UI is shown to speed up initial render
        self.root.after(800, self._deferred_executables_check)


        self.settings = load_settings()
        self.history = []
        self._history_loaded = False

        ctk.set_appearance_mode(self.settings.get("theme", "dark"))

        self.download_proc = DownloadProcess()
        self._executor = None
        self.ui_queue = queue.Queue()
        self.current_task_cancelled = False

        # caches and mappings
        self._history_thumb_imgs = {}
        self._playlist_thumb_imgs = {}
        self._playlist_row_by_vid = {}
        self._playlist_row_order = []



        self._build_skeleton_ui()
        self.root.after(50, self._build_ui)
        self.root.after(150, self._enable_mica_effect)
        self.root.after(100, self._process_ui_queue)

        # Show window after setup to avoid flashing
        self.root.after(0, self._show_window_after_setup)

    def _build_skeleton_ui(self):
        """Build minimal UI shell for fast startup."""
        self._create_titlebar()
        self.tabs = ctk.CTkTabview(self.root, width=980, height=540, corner_radius=12)
        self.tabs.pack(padx=12, pady=6, fill="both", expand=True)

        for name in (
            "Single Video",
            "Batch Downloader",
            "Playlist Downloader",
            "History",
            "Settings",
            "Update",
        ):
            self.tabs.add(name)


    def _check_for_updates(self):
        """Check GitHub API for newer releases."""
        import requests
        try:
            self.update_status_label.configure(text="Checking GitHub...")
            r = requests.get(GITHUB_API_LATEST, timeout=6)
            if r.status_code != 200:
                self.update_status_label.configure(text=f"Failed to fetch release info ({r.status_code})")
                return
            data = r.json()
            latest = data.get("tag_name", "").lstrip("v")
            if not latest:
                self.update_status_label.configure(text="No valid release found.")
                return
            if latest == APP_VERSION:
                self.update_status_label.configure(text=f"✅ You’re running the latest version ({APP_VERSION}).")
            else:
                self.update_status_label.configure(
                    text=f"🆕 New version available: {latest}\n(Current: {APP_VERSION})"
                )
                self.latest_release_data = data
        except Exception as e:
            self.update_status_label.configure(text=f"Failed to check updates: {e}")
        

    def _check_update_button(self):
        threading.Thread(target=self._check_for_updates, daemon=True).start()

    def _download_and_install_update(self):
        import requests
        import shutil
        """Download latest EXE and replace the current one."""
        try:
            data = getattr(self, "latest_release_data", None)
            if not data:
                messagebox.showinfo(APP_NAME, "Please check for updates first.")
                return
            assets = data.get("assets", [])
            exe_url = None
            for asset in assets:
                if asset["name"].endswith(".exe"):
                    exe_url = asset["browser_download_url"]
                    break
            if not exe_url:
                messagebox.showinfo(APP_NAME, "No .exe found in latest release assets.")
                return

            try: self.show_spinner("Downloading latest version...")
            except Exception: pass
            new_exe_path = TEMP_DIR / "Clipster_Update.exe"
            with requests.get(exe_url, stream=True, timeout=30) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", 0))
                with open(new_exe_path, "wb") as f:
                    downloaded = 0
                    for chunk in r.iter_content(chunk_size=8192):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            percent = downloaded * 100 // total
                            self.update_status_label.configure(text=f"Downloading... {percent}%")

            try: self.hide_spinner()
            except Exception: pass
            self.update_status_label.configure(text="✅ Download complete. Installing update...")

            # Run new exe and exit current app
            os.startfile(str(new_exe_path))
            self._close_window()

        except Exception as e:
            self.hide_spinner()
            messagebox.showerror(APP_NAME, f"Update failed: {e}")

    def _deferred_executables_check(self):
        try:
            missing = check_executables()
            if missing:
                _toast(self, f"Missing executables: {', '.join(missing)}", title="Assets")
                log_message(f"Missing executables: {missing}")
                # disable buttons that require executables
                def disable_controls():
                    # single tab download buttons
                    try:
                        self.single_download_btn.configure(state="disabled")
                    except Exception:
                        pass
                    try:
                        self.single_cancel_btn.configure(state="disabled")
                    except Exception:
                        pass
                    # ffplay preview
                    try:
                        # store missing set to check before preview
                        self._missing_exes = set(missing)
                        if "ffplay.exe" in missing:
                            # you had a preview button in playlist; detect and disable play preview operations
                            pass
                    except Exception:
                        pass
                self.safe_ui_call(disable_controls)
        except Exception as e:
            log_message(f"_deferred_executables_check error: {e}")



    def _show_window_after_setup(self):
        """Show the window after initial setup to reduce flashing."""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _create_titlebar(self):
        """Create a custom titlebar with Windows 11 styling."""
        import ctypes
        from ctypes import wintypes

        # Hide native titlebar
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        GWL_STYLE = -16
        WS_OVERLAPPEDWINDOW = 0x00CF0000
        WS_VISIBLE = 0x10000000
        WS_POPUP = 0x80000000

        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
        style = style & ~WS_OVERLAPPEDWINDOW | WS_POPUP | WS_VISIBLE
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style)
        ctypes.windll.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0027)

        # Add rounded corners
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(ctypes.c_int(DWMWCP_ROUND)), ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass

        # Build custom titlebar frame
        self.titlebar_frame = ctk.CTkFrame(self.root, height=32, corner_radius=0)
        self.titlebar_frame.pack(fill="x", side="top")

        self._update_titlebar_theme()

        # Left: icon + title
        left = ctk.CTkFrame(self.titlebar_frame, fg_color="transparent")
        left.pack(side="left", padx=(8, 4), pady=2)

        icon_img = None
        ico_path = BASE_DIR / "Assets" / "clipster.ico"

        # Set icon immediately without PIL
        try:
            if ico_path.exists():
                self.root.iconbitmap(default=str(ico_path))
        except Exception:
            pass

        # Defer PNG thumbnail creation
        def load_titlebar_icon():
            try:
                png_path = BASE_DIR / "Assets" / "clipster.png"
                if png_path.exists():
                    Image = get_pil_image()
                    img = Image.open(png_path).convert("RGBA")
                    img.thumbnail((20, 20))
                    icon_img = ctk.CTkImage(img, size=(20, 20))
                    icon_lbl.configure(image=icon_img)
                    icon_lbl.image = icon_img
            except Exception:
                pass

        # Create placeholder first
        icon_lbl = ctk.CTkLabel(left, text="▶", font=ctk.CTkFont(size=13))
        icon_lbl.pack(side="left", pady=1)

        # Load actual icon after 200ms
        self.root.after(200, load_titlebar_icon)

        if icon_img:
            icon_lbl = ctk.CTkLabel(left, image=icon_img, text="")
            icon_lbl.image = icon_img
            icon_lbl.pack(side="left", pady=1)
        else:
            icon_lbl = ctk.CTkLabel(left, text="▶", font=ctk.CTkFont(size=13))
            icon_lbl.pack(side="left")

        self._title_lbl = ctk.CTkLabel(left, text=APP_NAME, font=ctk.CTkFont(size=12, weight="bold"))
        self._title_lbl.pack(side="left", padx=(6, 2))
        self._subtitle_lbl = ctk.CTkLabel(left, text=SPLASH_TEXT, font=ctk.CTkFont(size=10))
        self._subtitle_lbl.pack(side="left")

        # Center drag zone
        drag_zone = ctk.CTkFrame(self.titlebar_frame, fg_color="transparent", height=1)
        drag_zone.pack(side="left", fill="both", expand=True)

        for w in (drag_zone, self._title_lbl, self._subtitle_lbl, icon_lbl):
            w.bind("<ButtonPress-1>", self._begin_native_drag)
            w.bind("<Double-Button-1>", lambda e: self._toggle_max_restore())

        # Right buttons
        btns = ctk.CTkFrame(self.titlebar_frame, fg_color="transparent")
        btns.pack(side="right", padx=2, pady=2)

        self._min_btn = ctk.CTkButton(
            btns, text="🗕", width=26, height=24, corner_radius=4,
            fg_color="transparent", hover_color="#2D2D2D",
            command=self._minimize_window
        )
        self._min_btn.pack(side="left", padx=(2, 0))

        self._max_btn = ctk.CTkButton(
            btns, text="🗖", width=26, height=24, corner_radius=4,
            fg_color="transparent", hover_color="#2D2D2D",
            command=self._toggle_max_restore
        )
        self._max_btn.pack(side="left", padx=1)

        self._close_btn = ctk.CTkButton(
            btns, text="✕", width=26, height=24, corner_radius=4,
            fg_color="transparent", hover_color="tomato",
            command=self._close_window
        )
        self._close_btn.pack(side="left", padx=(1, 4))

        self._is_maximized = False

    def _enable_mica_effect(self):
        """Enable Mica effect on Windows 11."""
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())

        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMWA_MICA_EFFECT = 1029
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMSBT_MAINWINDOW = 2

        try:
            dark_mode = 1 if self.settings.get("theme", "dark") == "dark" else 0
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(ctypes.c_int(dark_mode)), ctypes.sizeof(ctypes.c_int)
            )
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_SYSTEMBACKDROP_TYPE, ctypes.byref(ctypes.c_int(DWMSBT_MAINWINDOW)), ctypes.sizeof(ctypes.c_int)
            )
        except Exception as e:
            log_message(f"[Mica] Warning: could not enable Mica effect: {e}")

    def _begin_native_drag(self, event):
        """Start native window drag using Windows API."""
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        WM_SYSCOMMAND = 0x0112
        SC_MOVE = 0xF010
        HTCAPTION = 0x0002
        ctypes.windll.user32.ReleaseCapture()
        ctypes.windll.user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_MOVE + HTCAPTION, 0)

    def _toggle_max_restore(self):
        """Toggle maximize/restore window state."""
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())

        if not self._is_maximized:
            self._prev_geom = self.root.geometry()
            ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            self._is_maximized = True
            self._max_btn.configure(text="🗗")
        else:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            self._is_maximized = False
            self._max_btn.configure(text="🗖")
        self._animate_window("show")

    def _minimize_window(self):
        """Minimize the window with animation."""
        self._animate_window("hide")
        self.root.iconify()

    def _close_window(self):
        try:
            self.graceful_shutdown()
        except Exception:
            pass
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass

    def graceful_shutdown(self):
        """Safely shut down downloads, background workers, and temp files."""
        try:
            self.current_task_cancelled = True

            # Cancel active yt-dlp process
            try:
                if self.download_proc:
                    self.download_proc.cancel()
                    self.download_proc.shutdown()
            except Exception:
                pass

            # Shut down executor safely
            executor = getattr(self, "_executor", None)
            if executor:
                try:
                    executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    # Python < 3.9 fallback
                    executor.shutdown(wait=False)
                except Exception:
                    pass
                finally:
                    self._executor = None

        except Exception as e:
            log_message(f"graceful_shutdown error: {e}")

        # Cleanup old temp files (best-effort)
        try:
            for p in TEMP_DIR.iterdir():
                try:
                    if p.is_file() and (time.time() - p.stat().st_mtime) > 24 * 60 * 60:
                        p.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            pass



    def _animate_window(self, action="show"):
        """Animate window show/hide using Windows API."""
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())

        AW_BLEND = 0x00080000
        AW_CENTER = 0x00000010
        AW_HIDE = 0x00010000
        AW_ACTIVATE = 0x00020000

        flags = AW_BLEND | AW_CENTER | (AW_HIDE if action == "hide" else AW_ACTIVATE)
        try:
            ctypes.windll.user32.AnimateWindow(hwnd, 200, flags)
        except Exception:
            pass

    def _safe_create_ctkimage(self, img_path, size):
        """Safely create CTkImage from path."""
        try:
            Image = get_pil_image()
            img = Image.open(img_path).convert("RGBA")
            img.thumbnail(size)
            ctkimg = ctk.CTkImage(img, size=size)
            return ctkimg
        except Exception as e:
            log_message(f"_safe_create_ctkimage error for {img_path}: {e}")
            return None

    def _path_exists(self, p):
        return Path(str(p)).exists() if p else False

    def _set_label_image_from_path(self, label, path, size=(160, 90), fallback_text="No thumbnail"):
        """Set CTkLabel image from path."""
        try:
            if not path or not Path(str(path)).exists():
                label.configure(text=fallback_text, image=None)
                label.image = None
                return False
            ctkimg = self._safe_create_ctkimage(str(path), size)
            if ctkimg:
                label.configure(image=ctkimg, text="")
                label.image = ctkimg
                return True
            else:
                label.configure(text="Thumb error", image=None)
                label.image = None
                return False
        except Exception:
            try:
                label.configure(text="Thumb error", image=None)
                label.image = None
            except Exception:
                pass
            return False
        
    def _apply_theme(self):
        """Apply theme to the application. (override to recreate drag ghost to avoid desync)"""
        ctk.set_appearance_mode(self.settings.get("theme", "dark"))
        try:
            self.root.configure(fg_color=ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
        except Exception:
            pass
        if not self._history_loaded:
            self.root.after(300, self.load_and_render_history)
        self._update_titlebar_theme()
        self._enable_mica_effect()
        self.root.update_idletasks()

    def _on_theme_combo_changed(self, choice):
        """Called when the user picks a new theme from the combo box."""
        self.settings["theme"] = choice
        ctk.set_appearance_mode(choice)      # instant switch
        self._apply_theme()                  # update title-bar, Mica, etc.
        _toast(self, f"Theme changed to {choice}.", title="Theme")


    def _update_titlebar_theme(self):
        """Update titlebar colors based on theme."""
        theme = self.settings.get("theme", "dark")
        if theme == "light":
            bg = "#f2f2f2"
            fg = "#000000"          # dark text / icons
            btn_hover = "#dddddd"
        else:
            bg = "#202020"
            fg = "#ffffff"
            btn_hover = "#2D2D2D"

        try:
            self.titlebar_frame.configure(fg_color=bg)
            self._title_lbl.configure(text_color=fg)
            self._subtitle_lbl.configure(text_color=fg)

            # ---- force button colours ----
            for btn in (self._min_btn, self._max_btn, self._close_btn):
                btn.configure(text_color=fg, hover_color=btn_hover)
                # close button stays red on hover
                if btn == self._close_btn:
                    btn.configure(hover_color="tomato")
        except Exception:
            pass

    def _show_custom_dropdown(self, parent_widget, values, on_select):
        """Show custom dropdown menu."""
        import ctypes

        menu_win = ctk.CTkToplevel(self.root)
        menu_win.overrideredirect(True)
        menu_win.attributes("-topmost", True)
        menu_win.wm_attributes("-alpha", 0.0)
        theme = self.settings["theme"]
        fg_color = "#f9f9f9" if theme == "light" else "#1f1f1f"
        hover_color = "#e0e0e0" if theme == "light" else "#2b2b2b"
        menu_win.configure(fg_color=fg_color)

        # Rounded corners
        try:
            hwnd = ctypes.windll.user32.GetParent(menu_win.winfo_id())
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(ctypes.c_int(DWMWCP_ROUND)), ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass

        # Position below parent
        x = parent_widget.winfo_rootx()
        y = parent_widget.winfo_rooty() + parent_widget.winfo_height()
        menu_win.geometry(f"+{x}+{y}")

        # Add buttons
        for val in values:
            btn = ctk.CTkButton(
                menu_win, 
                text=val, 
                fg_color="transparent", 
                hover_color=hover_color, 
                anchor="w",
                width=parent_widget.winfo_width() - 8, 
                height=32, 
                corner_radius=8,  # ADD corner_radius=8
                command=lambda v=val: (on_select(v), menu_win.destroy())
            )
            btn.pack(fill="x", padx=6, pady=2)

        

        # Fade in
        alpha_step = 0.08
        current_alpha = 0.0
        def fade_in():
            nonlocal current_alpha
            if current_alpha < 0.96:
                current_alpha += alpha_step
                menu_win.attributes("-alpha", min(current_alpha, 0.96))
                menu_win.after(20, fade_in)
            else:
                menu_win.attributes("-alpha", 0.96)

        menu_win.after(10, fade_in)

        # Close on focus out
        def close_on_focus_out(e=None):
            try:
                menu_win.destroy()
            except Exception:
                pass

        menu_win.bind("<FocusOut>", close_on_focus_out)
        menu_win.focus_force()

    def _show_custom_menu(self, event, items):
        """Show custom context menu."""
        import ctypes

        menu_win = ctk.CTkToplevel(self.root)
        menu_win.overrideredirect(True)
        menu_win.attributes("-topmost", True)
        theme = self.settings["theme"]
        fg_color = "#f9f9f9" if theme == "light" else "#1f1f1f"
        hover_color = "#e0e0e0" if theme == "light" else "#2b2b2b"
        menu_win.configure(fg_color=fg_color)
        menu_win.wm_attributes("-alpha", 0.96)

        # Rounded corners
        try:
            hwnd = ctypes.windll.user32.GetParent(menu_win.winfo_id())
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(ctypes.c_int(DWMWCP_ROUND)), ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass

        # Add items
        for label, callback in items:
            btn = ctk.CTkButton(
                menu_win, 
                text=label, 
                fg_color="transparent", 
                hover_color=hover_color, 
                anchor="w",
                width=180, 
                height=32, 
                corner_radius=8,  # ADD corner_radius=8
                command=lambda c=callback, 
                m=menu_win: (m.destroy(), c())
            )
            btn.pack(fill="x", padx=8, pady=2)

        # Position at mouse
        x, y = event.x_root, event.y_root
        menu_win.geometry(f"+{x}+{y}")

        # Close on focus out
        def close_on_focus_out(e=None):
            try:
                menu_win.destroy()
            except Exception:
                pass

        menu_win.bind("<FocusOut>", close_on_focus_out)
        menu_win.focus_force()

    def _build_ui(self):
        """Populate tab contents (called after skeleton UI is visible)."""
        try:
            self._build_single_tab(self.tabs.tab("Single Video"))
            self._build_batch_tab(self.tabs.tab("Batch Downloader"))
            self._build_playlist_tab(self.tabs.tab("Playlist Downloader"))
            self._build_history_tab(self.tabs.tab("History"))
            self._build_settings_tab(self.tabs.tab("Settings"))
            self._build_update_tab(self.tabs.tab("Update"))

            self.status_var = None
            self.cancel_btn = None
            self.spinner_overlay = None

        except Exception as e:
            log_message(f"_build_ui error: {e}")

    def _build_single_tab(self, parent):
        """Build UI for Single Video tab."""
        pad = 12
        frame = ctk.CTkFrame(parent, corner_radius=12)
        frame.pack(fill="both", expand=True, padx=pad, pady=pad)
        left = ctk.CTkFrame(frame, corner_radius=10)
        left.pack(side="left", fill="y", padx=(0, 8), pady=4)

        url_frame = ctk.CTkFrame(left, fg_color="transparent")
        url_frame.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(url_frame, text="Video URL:", anchor="w", width=100).pack(side="left", padx=(0, 8))
        self.single_url_entry = ctk.CTkEntry(url_frame, width=400, height=36, corner_radius=8)
        self.single_url_entry.pack(side="left", fill="x", expand=True)

        self.fetch_meta_btn = ctk.CTkButton(left, text="Fetch Metadata", fg_color=ACCENT_COLOR, 
                                     height=36, corner_radius=8, command=self.on_fetch_single_metadata)
        self.fetch_meta_btn.pack(padx=8, pady=6)

        self.save_thumb_btn = ctk.CTkButton(left, text="Save Thumbnail", fg_color="gray", 
                                            height=36, corner_radius=8, command=self.on_save_thumbnail)
        self.save_thumb_btn.pack(padx=8, pady=(0,6))
        self.save_thumb_btn.configure(state="disabled")

        res_frame = ctk.CTkFrame(left, fg_color="transparent")
        res_frame.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(res_frame, text="Resolution:", anchor="w", width=100).pack(side="left", padx=(0, 8))
        self.single_resolution_combo = ctk.CTkComboBox(res_frame, values=["Best Available"], width=250, 
                                                        height=36, corner_radius=8)
        self.single_resolution_combo.set("Best Available")
        self.single_resolution_combo.pack(side="left")

        fmt_frame = ctk.CTkFrame(left, fg_color="transparent")
        fmt_frame.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(fmt_frame, text="Format:", anchor="w", width=100).pack(side="left", padx=(0, 8))
        self.single_format_combo = ctk.CTkComboBox(fmt_frame, values=ALLOWED_FORMATS, width=250, 
                                                    height=36, corner_radius=8)
        self.single_format_combo.set(self.settings.get("default_format", "mp4"))
        self.single_format_combo.pack(side="left")

        

        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.pack(padx=8, pady=(4, 12))
        self.single_download_btn = ctk.CTkButton(btn_frame, text="Download", fg_color=ACCENT_COLOR, height=36, corner_radius=8, command=self.on_single_download)
        self.single_download_btn.pack(side="left", padx=6)
        self.single_cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", height=36, corner_radius=8, command=self.cancel_download)
        self.single_cancel_btn.pack(side="left", padx=6)

        

        self.single_pause_btn = ctk.CTkButton(
            btn_frame,
            text="Pause",
            height=36,
            corner_radius=8,
            command=self.pause_download
        )
        self.single_pause_btn.pack(side="left", padx=6)
        self.single_pause_btn.configure(state="disabled")

        ctk.CTkLabel(left, text="Progress:", anchor="w").pack(padx=8, pady=(6, 0))
        self.single_progress = ctk.CTkProgressBar(left, width=320, height=8, corner_radius=4)
        self.single_progress.set(0)
        self.single_progress.pack(padx=8, pady=(4, 8))
        self.single_progress_label = ctk.CTkLabel(left, text="")
        self.single_progress_label.pack(padx=8, pady=(2, 8))

        right = ctk.CTkFrame(frame, corner_radius=10)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=4)

        self.meta_title_var = ctk.StringVar(value="")
        self.meta_title_label = ctk.CTkLabel(
            right,
            textvariable=self.meta_title_var,
            font=ctk.CTkFont(size=16, weight="bold"),
            wraplength=420,  # adjust width limit
            justify="left",
            anchor="nw"
        )
        self.meta_title_label.pack(anchor="nw", padx=8, pady=(8, 0), fill="x")

        self.meta_uploader_var = ctk.StringVar(value="")
        ctk.CTkLabel(right, textvariable=self.meta_uploader_var, font=ctk.CTkFont(size=12)).pack(anchor="nw", padx=8, pady=2)
        self.meta_duration_var = ctk.StringVar(value="")
        ctk.CTkLabel(right, textvariable=self.meta_duration_var, font=ctk.CTkFont(size=12)).pack(anchor="nw", padx=8, pady=2)

        self.thumbnail_label = ctk.CTkLabel(right, text="Thumbnail preview", width=320, height=180, anchor="center", corner_radius=10)
        self.thumbnail_label.pack(anchor="nw", padx=8, pady=12)

    def on_save_thumbnail(self):
        import shutil
        """Save the last fetched thumbnail safely to the configured download folder."""
        try:
            target_dir = Path(self.settings.get("default_download_path", str(DOWNLOADS_DIR)))
            target_dir.mkdir(parents=True, exist_ok=True)

            # prefer existing image
            cur_img = getattr(self.thumbnail_label, "image_path", None)
            if cur_img and os.path.exists(cur_img):
                out = target_dir / Path(cur_img).name
                shutil.copyfile(cur_img, out)
                _toast(self, f"Thumbnail saved: {out}", title="Thumbnail")
                return

            # fallback to last metadata
            if hasattr(self, "_last_meta"):
                turl = self._last_meta.get("thumbnail")
                if turl:
                    vid = self._extract_video_id(self.single_url_entry.get().strip()) or int(time.time())
                    target = target_dir / f"{vid}_thumbnail.jpg"
                    thumb_path = download_thumbnail(turl, str(target))
                    if thumb_path:
                        _toast(self, f"Thumbnail saved: {target}", title="Thumbnail")
                        return

            _toast(self, "No thumbnail available to save.", title="Thumbnail", level="error")
        except Exception as e:
            log_message(f"on_save_thumbnail error: {e}")
            _toast(self, "Failed to save thumbnail.", title="Thumbnail", level="error")


    def _build_batch_tab(self, parent):
        """Build UI for Batch Downloader tab."""
        pad = 12
        frame = ctk.CTkFrame(parent, corner_radius=12)
        frame.pack(fill="both", expand=True, padx=pad, pady=pad)
        top = ctk.CTkFrame(frame, corner_radius=10)
        top.pack(fill="x", pady=6)
        ctk.CTkLabel(top, text="Paste multiple video URLs (one per line):").pack(side="left", padx=6)
        self.batch_maxres_combo = ctk.CTkComboBox(top, values=["Best Available", "720p", "1080p", "1440p", "2160p"], width=180, height=36, corner_radius=8)
        self.batch_maxres_combo.set("Best Available")
        self.batch_maxres_combo.pack(side="right", padx=6)

        self.batch_text = ctk.CTkTextbox(frame, width=800, height=260, corner_radius=10)
        self.batch_text.pack(padx=6, pady=6, fill="both", expand=True)

        bottom = ctk.CTkFrame(frame, corner_radius=10)
        bottom.pack(fill="x", pady=6)
        ctk.CTkLabel(bottom, text="Format:").pack(side="left", padx=6)
        self.batch_format_combo = ctk.CTkComboBox(bottom, values=ALLOWED_FORMATS, height=36, corner_radius=8)
        self.batch_format_combo.set(self.settings.get("default_format", "mp4"))
        self.batch_format_combo.pack(side="left", padx=6)
        ctk.CTkButton(
            bottom,
            text="Download Batch",
            fg_color=ACCENT_COLOR,
            height=36,
            corner_radius=8,
            command=self.on_batch_download
        ).pack(side="right", padx=6)



        ctk.CTkLabel(
            frame,
            text="Overall Progress:",
            text_color="#A0A0A0",
            anchor="w"
        ).pack(anchor="w", padx=6, pady=(6, 0))

        self.batch_overall_progress = ctk.CTkProgressBar(
            frame, 
            height=8, 
            fg_color="#2E2E2E",
            progress_color=ACCENT_COLOR, 
            corner_radius=4
        )

        self.batch_overall_progress.set(0)
        self.batch_overall_progress.pack(fill="x", padx=6, pady=(0, 10))


    def _build_playlist_tab(self, parent):
        """Build UI for Playlist Downloader tab."""
        pad = 12
        frame = ctk.CTkFrame(parent, corner_radius=12)
        frame.pack(fill="both", expand=True, padx=pad, pady=pad)

        url_frame = ctk.CTkFrame(frame, fg_color="transparent")
        url_frame.pack(fill="x", padx=6, pady=(6, 4))
        ctk.CTkLabel(url_frame, text="Playlist URL:", anchor="w", width=100).pack(side="left", padx=(0, 8))
        self.playlist_url_entry = ctk.CTkEntry(url_frame, width=600, height=36, corner_radius=8)
        self.playlist_url_entry.pack(side="left", fill="x", expand=True)

        fetch_btn = ctk.CTkButton(
            frame, 
            text="Fetch Playlist Items", 
            fg_color=ACCENT_COLOR, 
            height=36, 
            corner_radius=8, 
            command=self.on_fetch_playlist
        )
        fetch_btn.pack(padx=6, pady=(4, 8))

        self.playlist_progress_label = ctk.CTkLabel(frame, text="", anchor="w")
        self.playlist_progress_label.pack(anchor="nw", padx=6, pady=(4, 0))

        ctk.CTkLabel(frame, text="Playlist Items:").pack(anchor="nw", padx=6, pady=(6, 0))
        self.playlist_scroll = ctk.CTkScrollableFrame(frame, height=280, corner_radius=10)
        self.playlist_scroll.pack(fill="both", expand=True, padx=6, pady=(4, 12))

        bottom = ctk.CTkFrame(frame, corner_radius=10)
        bottom.pack(fill="x", pady=6)
        ctk.CTkLabel(bottom, text="Max Resolution:").pack(side="left", padx=6)
        self.playlist_maxres_combo = ctk.CTkComboBox(bottom, values=["Best Available", "720p", "1080p", "1440p", "2160p"], width=180)
        self.playlist_maxres_combo.set("Best Available")
        self.playlist_maxres_combo.pack(side="left", padx=6)
        ctk.CTkLabel(bottom, text="Format:").pack(side="left", padx=6)
        self.playlist_format_combo = ctk.CTkComboBox(bottom, values=ALLOWED_FORMATS)
        self.playlist_format_combo.set(self.settings.get("default_format", "mp4"))
        self.playlist_format_combo.pack(side="left", padx=6)
        
        sel_frame = ctk.CTkFrame(frame, fg_color="transparent")
        sel_frame.pack(fill="x", padx=6, pady=(0,6))
        ctk.CTkButton(sel_frame, text="Select All", fg_color=ACCENT_COLOR, command=self.playlist_select_all).pack(side="left", padx=(0,6))
        ctk.CTkButton(sel_frame, text="Deselect All", fg_color="gray", command=self.playlist_deselect_all).pack(side="left", padx=6)
        ctk.CTkButton(sel_frame, text="Save selection as .txt", fg_color=SECONDARY_COLOR, command=self.playlist_save_selection).pack(side="left", padx=6)

        ctk.CTkButton(
            bottom,
            text="Download Playlist",
            fg_color=ACCENT_COLOR,
            command=self.on_download_playlist
        ).pack(side="right", padx=6)

        # --- Overall progress placed BELOW everything ---
        progress_container = ctk.CTkFrame(parent, fg_color="transparent")
        progress_container.pack(fill="x", pady=(6, 8), side="bottom")

        ctk.CTkLabel(
            progress_container,
            text="Overall Progress:",
            text_color="#A0A0A0",
            anchor="w"
        ).pack(anchor="w", padx=6, pady=(4, 0))

        self.playlist_overall_progress = ctk.CTkProgressBar(
            progress_container,
            height=10,
            fg_color="#2E2E2E",
            progress_color=ACCENT_COLOR,
            corner_radius=8
        )
        self.playlist_overall_progress.set(0)
        self.playlist_overall_progress.pack(fill="x", padx=6, pady=(0, 8))


    def _build_history_tab(self, parent):
        """Build UI for History tab."""
        frame = ctk.CTkFrame(parent, corner_radius=12)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        top = ctk.CTkFrame(frame, corner_radius=10)
        top.pack(fill="x", pady=(0, 8))
        ctk.CTkButton(
            top, 
            text="Clear History", 
            command=self.clear_history_prompt, 
            fg_color="tomato", 
            height=36, 
            corner_radius=8
        ).pack(side="right", padx=8, pady=6)

        self.history_scroll = ctk.CTkScrollableFrame(frame, height=480, corner_radius=10)
        self.history_scroll.pack(fill="both", expand=True, padx=6, pady=6)

        if not self._history_loaded:
            self.root.after(300, self.load_and_render_history)

    def refresh_history(self):
        """Refresh history list UI."""
        for widget in list(self.history_scroll.winfo_children()):
            try:
                if widget.winfo_exists():
                    widget.destroy()
            except Exception:
                pass
        self._history_thumb_imgs.clear()
        self.history = load_history()
        if not self.history:
            lbl = ctk.CTkLabel(self.history_scroll, text="No history yet.", anchor="center")
            lbl.pack(pady=12)
            return

        for idx, entry in enumerate(self.history):
            row = self._create_history_row(idx, entry)
            row.pack(fill="x", pady=6, padx=6)

            def thumb_task(i, ent):
                try:
                    thumb_path = None
                    url = ent.get("url", "")
                    vid = self._extract_video_id(url)
                    if vid:
                        for p in TEMP_DIR.glob(f"*{vid}*"):
                            if p.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                                thumb_path = str(p)
                                break
                    if not thumb_path:
                        title = ent.get("title", "")
                        safe_title_frag = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
                        if safe_title_frag:
                            for p in TEMP_DIR.iterdir():
                                if p.is_file() and safe_title_frag[:10].lower() in p.name.lower():
                                    if p.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                                        thumb_path = str(p)
                                        break
                    if not thumb_path:
                        try:
                            meta = fetch_metadata_via_yt_dlp(url, timeout=18)
                            if meta:
                                turl = meta.get("thumbnail")
                                if turl:
                                    target = TEMP_DIR / f"hist_thumb_{vid or i}.jpg"
                                    ok = download_thumbnail(turl, str(target))
                                    if ok:
                                        thumb_path = str(target)
                        except Exception:
                            thumb_path = None
                    self.ui_queue.put(("history_thumb_ready", i, thumb_path))
                except Exception:
                    self.ui_queue.put(("history_thumb_ready", i, None))

            #threading.Thread(target=thumb_task, args=(idx, entry), daemon=True).start()
            if getattr(self, "_executor", None):
                self.get_executor().submit(thumb_task, idx, entry)
            else:
                threading.Thread(target=thumb_task, args=(idx, entry), daemon=True).start()

    def load_and_render_history(self):
        """Load history in a background thread after startup."""
        if self._history_loaded:
            return
        try:
            time.sleep(0.1)  # Small delay to let UI settle
            self.history = load_history()
            self._history_loaded = True
            self.safe_ui_call(self.refresh_history)
        except Exception as e:
            log_message(f"load_and_render_history failed: {e}")


    def _create_history_row(self, idx, entry):
        """Create a row for history item."""
        row_frame = ctk.CTkFrame(self.history_scroll, height=100, corner_radius=10)
        row_frame.grid_columnconfigure(1, weight=1)

        thumb_label = ctk.CTkLabel(
            row_frame, 
            text="No\nthumbnail", 
            width=140, 
            height=80, 
            anchor="center", 
            corner_radius=8
        )
        thumb_label.grid(row=0, column=0, rowspan=2, padx=(8,10), pady=8)

        title = entry.get("title", "<No title>")
        uploader = entry.get("uploader", "")
        res = entry.get("resolution", "")
        date = entry.get("date", "")
        info_text = f"{uploader} • {res} • {date}"
        title_lbl = ctk.CTkLabel(row_frame, text=title, anchor="w", font=ctk.CTkFont(size=13, weight="bold"))
        title_lbl.grid(row=0, column=1, sticky="w", padx=(0,8), pady=(8,0))
        info_lbl = ctk.CTkLabel(row_frame, text=info_text, anchor="w", font=ctk.CTkFont(size=10))
        info_lbl.grid(row=1, column=1, sticky="w", padx=(0,8), pady=(0,8))

        btn_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
        btn_frame.grid(row=0, column=2, rowspan=2, padx=8, pady=8)
        redl_btn = ctk.CTkButton(
            btn_frame, 
            text="Re-Download", 
            fg_color=ACCENT_COLOR, 
            width=110, 
            height=32, 
            corner_radius=8, 
            command=lambda e=entry, 
            i=idx: self.re_download(e, i)
        )
        redl_btn.pack(pady=(6,4))
        del_btn = ctk.CTkButton(
            btn_frame, 
            text="Delete", 
            fg_color="tomato", 
            width=110, 
            height=32, 
            corner_radius=8, 
            command=lambda i=idx: (delete_history_entry(i), self.refresh_history())
        )
        del_btn.pack(pady=(4,6))

        row_frame._thumb_label = thumb_label
        row_frame._entry = entry
        row_frame._index = idx

        return row_frame

    def _extract_video_id(self, url):
        """Extract video ID from YouTube URL."""
        from urllib.parse import urlparse, parse_qs

        try:
            u = (url or "").strip()
            parsed = urlparse(u)
            if parsed.netloc and "youtu.be" in parsed.netloc:
                return parsed.path.lstrip("/")
            qs = parse_qs(parsed.query)
            if "v" in qs and qs["v"]:
                return qs["v"][0]
            m = re.search(r"(?:v=|/vi?/|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})", u)
            if m:
                return m.group(1)
            return None
        except Exception:
            return None

    def clear_history_prompt(self):
        """Prompt to clear history."""
        if messagebox.askyesno(APP_NAME, "Clear entire download history?"):
            clear_history()
            self.refresh_history()

    def _build_update_tab(self, parent):
        import webbrowser
        """Build the Update tab (checks GitHub for latest release)."""
        frame = ctk.CTkFrame(parent, corner_radius=12)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        title = ctk.CTkLabel(frame, text="Check for Updates", font=ctk.CTkFont(size=18, weight="bold"))
        title.pack(pady=(10, 4))

        self.update_status_label = ctk.CTkLabel(frame, text="Checking for updates...", wraplength=480)
        self.update_status_label.pack(pady=8)

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(pady=10)

        self.update_check_btn = ctk.CTkButton(
            btn_frame, text="🔄 Recheck", fg_color=ACCENT_COLOR, command=self._check_update_button
        )
        self.update_check_btn.pack(side="left", padx=6)

        self.update_download_btn = ctk.CTkButton(
            btn_frame, text="⬇️ Download & Install", fg_color=SECONDARY_COLOR, command=self._download_and_install_update
        )
        self.update_download_btn.pack(side="left", padx=6)

        self.update_open_btn = ctk.CTkButton(
            btn_frame, text="🌐 Open GitHub Page", fg_color="gray", command=lambda: webbrowser.open(GITHUB_RELEASES_URL)
        )
        self.update_open_btn.pack(side="left", padx=6)

        # Check for updates on load
        #threading.Thread(target=self._check_for_updates, daemon=True).start()


    # ──────────────────────────────────────────────────────────────
    #  SETTINGS TAB – replace the whole block that creates the format entry
    # ──────────────────────────────────────────────────────────────
    def _build_settings_tab(self, parent):
        """Build UI for Settings tab."""
        frame = ctk.CTkFrame(parent, corner_radius=12)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        # ---------- Default format ----------
        fmt_frame = ctk.CTkFrame(frame, fg_color="transparent")
        fmt_frame.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(fmt_frame, text="Default format:", anchor="w", width=150).pack(side="left", padx=(0, 8))
        self.settings_format_combo = ctk.CTkComboBox(fmt_frame, values=ALLOWED_FORMATS, width=180, height=36, corner_radius=8)
        self.settings_format_combo.set(self.settings.get("default_format", "mp4"))
        self.settings_format_combo.pack(side="left")

        # ---------- Theme (real ComboBox) ----------
        theme_frame = ctk.CTkFrame(frame, fg_color="transparent")
        theme_frame.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(theme_frame, text="Theme:", anchor="w", width=150).pack(side="left", padx=(0, 8))
        self.settings_theme_combo = ctk.CTkComboBox(theme_frame, values=["dark", "light"], width=120,
                                                    height=36, corner_radius=8, command=self._on_theme_combo_changed)
        self.settings_theme_combo.set(self.settings.get("theme", "dark"))
        self.settings_theme_combo.pack(side="left")

        
        
        # ---------- Default download folder ----------
        folder_frame = ctk.CTkFrame(frame, fg_color="transparent")
        folder_frame.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(folder_frame, text="Download folder:", anchor="w", width=150).pack(side="left", padx=(0, 8))
        self.default_download_path_entry = ctk.CTkEntry(folder_frame, width=400, height=36, corner_radius=8)
        self.default_download_path_entry.insert(0, self.settings.get("default_download_path", str(DOWNLOADS_DIR)))
        self.default_download_path_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(folder_frame, text="Browse", height=36, corner_radius=8, 
                    command=self.on_choose_download_folder).pack(side="left")

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(anchor="nw", padx=8, pady=(16, 6))

        ctk.CTkButton(btn_frame, text="Apply Settings", fg_color=ACCENT_COLOR, height=36, corner_radius=8, command=self.on_apply_settings).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_frame, text="Reset to Defaults", fg_color="gray", height=36, corner_radius=8, command=self.on_reset_defaults).pack(side="left", padx=4)
        ctk.CTkButton(btn_frame, text="Open Log File", fg_color=SECONDARY_COLOR, height=36, corner_radius=8, command=open_log_file).pack(side="left", padx=8)

    def on_apply_settings(self):
        """Apply and save settings."""
        self.settings["default_format"] = self.settings_format_combo.get()
        self.settings["theme"] = self.settings_theme_combo.get()
        self.settings["default_download_path"] = self.default_download_path_entry.get() or str(DOWNLOADS_DIR)
        save_settings(self.settings)
        log_message(f"Settings applied: {self.settings}")
        self._apply_theme()
        _toast(self, "Settings applied.", title="Settings")


    def on_reset_defaults(self):
        """Reset settings to defaults."""
        if messagebox.askyesno(APP_NAME, "Reset all settings to default values?"):
            save_settings(DEFAULT_SETTINGS)
            self.settings = DEFAULT_SETTINGS.copy()
            self.settings_format_combo.set("mp4")
            self.settings_theme_combo.set("dark")
            self.default_download_path_entry.delete(0, "end")
            self.default_download_path_entry.insert(0, WINDOWS_DOWNLOADS_DIR)
            log_message("Settings reset to defaults")
            self._apply_theme()
            _toast(self, "Settings reset to defaults.", title="Settings")


    def on_choose_download_folder(self):
        """Choose default download folder."""
        path = filedialog.askdirectory(initialdir=self.settings.get("default_download_path", WINDOWS_DOWNLOADS_DIR))
        if path:
            self.default_download_path_entry.delete(0, "end")
            self.default_download_path_entry.insert(0, path)

    def playlist_select_all(self):
        """Select all playlist items."""
        for vid, row in list(self._playlist_row_by_vid.items()):
            try:
                if hasattr(row, "_selected_var"):
                    row._selected_var.set(True)
            except Exception:
                pass

    def playlist_deselect_all(self):
        """Deselect all playlist items."""
        for vid, row in list(self._playlist_row_by_vid.items()):
            try:
                if hasattr(row, "_selected_var"):
                    row._selected_var.set(False)
            except Exception:
                pass

    def playlist_save_selection(self):
        """Save selected playlist URLs to text file."""
        selected = []
        for vid in list(self._playlist_row_order):
            row = self._playlist_row_by_vid.get(vid)
            if not row:
                continue
            sel = getattr(row, "_selected_var", None)
            if sel and sel.get():
                ent = getattr(row, "_entry", None)
                if ent:
                    selected.append(ent.get("url"))
        if not selected:
            messagebox.showinfo(APP_NAME, "No items selected to save.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files","*.txt")], title="Save selected URLs")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for u in selected:
                    f.write(u + "\n")
            messagebox.showinfo(APP_NAME, f"Saved {len(selected)} URLs to:\n{path}")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Failed to save selection: {e}")

    def show_spinner(self, text="Please wait..."):
        """Show spinner overlay with Windows 11 styling."""
        if self.spinner_overlay:
            return
        overlay = ctk.CTkToplevel(self.root)
        overlay.geometry("340x130")
        overlay.transient(self.root)
        overlay.grab_set()
        overlay.title("")
        overlay.attributes("-topmost", True)
        overlay.resizable(False, False)
        
        # ADD ROUNDED CORNERS HERE (before positioning)
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(overlay.winfo_id())
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(ctypes.c_int(DWMWCP_ROUND)), ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass
        
        # NOW position it
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 170  # Changed from 160 to 170
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 65  # Changed from 60 to 65
        overlay.geometry(f"+{x}+{y}")
        
        lbl = ctk.CTkLabel(overlay, text=text, font=ctk.CTkFont(size=14))
        lbl.pack(pady=(24, 8))  # Changed padding for better spacing
        pb = ctk.CTkProgressBar(overlay, mode="indeterminate", height=8, corner_radius=4) 
        pb.pack(fill="x", padx=24, pady=(4, 24))  # Changed bottom padding
        pb.start()
        self.spinner_overlay = overlay  

    def hide_spinner(self):
        """Hide spinner overlay."""
        if self.spinner_overlay:
            try:
                self.spinner_overlay.grab_release()
                self.spinner_overlay.destroy()
            except Exception:
                pass
            self.spinner_overlay = None

    def on_fetch_single_metadata(self):
        """Fetch metadata for single video."""
        url = self.single_url_entry.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "Please enter a video URL.")
            return
        if not is_youtube_url(url):
            messagebox.showwarning(APP_NAME, "URL does not look like a YouTube URL (basic check).")
            return
        self.fetch_meta_btn.configure(state="disabled")
        self.show_spinner("Fetching metadata...")
        def task():
            try:
                meta = fetch_metadata_via_yt_dlp(url)
                formats = meta.get("formats", [])
                resolutions = set()
                for f in formats:
                    h = f.get("height")
                    if h:
                        resolutions.add(f"{h}p")
                sorted_res = sorted([r for r in resolutions], key=lambda x: int(x.replace("p","")), reverse=True)
                if not sorted_res:
                    sorted_res = ["Best Available"]
                else:
                    sorted_res.insert(0, "Best Available")
                thumb_url = meta.get("thumbnail")
                thumb_local = None
                if thumb_url:
                    thumb_local = TEMP_DIR / f"thumb_{int(time.time())}.jpg"
                    ok = download_thumbnail(thumb_url, str(thumb_local))
                    if not ok:
                        thumb_local = None
                self.ui_queue.put(("meta_fetched", meta, sorted_res, str(thumb_local) if thumb_local else None))
            except Exception as e:
                self.ui_queue.put(("meta_error", str(e)))
        if getattr(self, "_executor", None):
            self.get_executor().submit(task)
        else:
            threading.Thread(target=task, daemon=True).start()

    def on_single_download(self):
        import shutil
        """Start download for single video."""
        url = self.single_url_entry.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "Please enter a video URL.")
            return
        fmt = self.single_format_combo.get()
        embed_thumb = False
        res_label = self.single_resolution_combo.get()
        outdir = self.settings.get("default_download_path", WINDOWS_DOWNLOADS_DIR)
        Path(outdir).mkdir(parents=True, exist_ok=True)
        total, used, free = shutil.disk_usage(outdir)
        if free < 500 * 1024 * 1024:
            messagebox.showwarning(APP_NAME, "Low disk space detected! You may run out during download.")
        fmt_selector = build_format_selector_for_format_and_res(fmt, res_label)
        if self.settings.get("use_smart_naming", True):
            filename_template = "%(uploader)s - %(title)s.%(ext)s"
        else:
            filename_template = "%(title)s.%(ext)s"
        self.single_download_btn.configure(state="disabled")
        # cancel button removed; notify user with a toast instead
        _toast(self, "Download started...", title="Download", timeout=3000)
        self.single_progress.set(0)
        self.single_progress_label.configure(text="Starting...")
        self.current_task_cancelled = False

        self.single_pause_btn.configure(state="normal")

        cookies_path = self.settings.get("cookies_path", "") or None

        def progress_callback(percent, speed, eta, raw_line):
            if percent is None:
                progress_value = 0.0
            else:
                progress_value = percent/100.0
            self.ui_queue.put(("single_progress", progress_value, speed, eta, raw_line))

        def finished_callback(output_path):
            self.ui_queue.put(("single_finished", output_path, fmt, embed_thumb, url))

        def error_callback(err):
            if "age-restricted" in str(err).lower() or "sign in to confirm your age" in str(err).lower() or "members-only" in str(err).lower():
                self.ui_queue.put(("single_error_restricted", str(err)))
            else:
                self.ui_queue.put(("single_error", str(err)))

        self.download_proc.start_download(url, outdir, filename_template, fmt_selector, cookies_path, progress_callback, finished_callback, error_callback)

    def on_batch_download(self):
        import shutil
        """Start batch download (sequential & stable)."""
        raw = self.batch_text.get("0.0", "end").strip()
        if not raw:
            messagebox.showwarning(APP_NAME, "Please paste at least one URL.")
            return
        urls = [line.strip() for line in raw.splitlines() if line.strip()]
        if not urls:
            messagebox.showwarning(APP_NAME, "No valid URLs detected.")
            return

        target_format = self.batch_format_combo.get()
        max_res = self.batch_maxres_combo.get()
        embed_thumb = False  # embed removed permanently
        outdir = self.settings.get("default_download_path", WINDOWS_DOWNLOADS_DIR)
        Path(outdir).mkdir(parents=True, exist_ok=True)
        total, used, free = shutil.disk_usage(outdir)
        if free < 500 * 1024 * 1024:
            messagebox.showwarning(APP_NAME, "Low disk space detected! You may run out during download.")

        fmt_selector = build_batch_format_selector(target_format, max_res)
        cookies_path = self.settings.get("cookies_path", "") or None

        self.batch_overall_progress.set(0)
        total_count = len(urls)
        completed = 0
        self.current_task_cancelled = False
        _toast(self, f"Downloading {total_count} videos...", title="Batch")

        self.single_pause_btn.configure(state="disabled")

        def batch_task():
            nonlocal completed
            for idx, url in enumerate(urls, start=1):
                if self.current_task_cancelled:
                    break

                self.ui_queue.put(("batch_item_start", idx, url))
                finished_event = threading.Event()
                out_path_holder = {"path": None}
                meta = {}

                def progress_callback(percent, speed, eta, raw_line):
                    pval = (percent or 0.0) / 100.0 if percent is not None else 0.0
                    self.ui_queue.put(("batch_item_progress", idx, pval, speed, eta))

                def finished_callback(output_path):
                    out_path_holder["path"] = output_path
                    finished_event.set()

                def error_callback(err):
                    self.ui_queue.put(("batch_item_error", idx, str(err)))
                    finished_event.set()

                filename_template = (
                    "%(uploader)s - %(title)s.%(ext)s"
                    if self.settings.get("use_smart_naming", True)
                    else "%(title)s.%(ext)s"
                )

                # Run single download
                self.download_proc.start_download(url, outdir, filename_template, fmt_selector,
                                                cookies_path, progress_callback, finished_callback, error_callback)

                while not finished_event.is_set():
                    if self.current_task_cancelled:
                        self.download_proc.cancel()
                        break
                    time.sleep(0.25)

                output_path = out_path_holder["path"]
                if not output_path:
                    try:
                        files = sorted(Path(outdir).glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
                        output_path = str(files[0]) if files else None
                    except Exception:
                        output_path = None

                # Append to history
                entry = {
                    "title": Path(output_path).stem if output_path else "",
                    "url": url,
                    "resolution": max_res,
                    "format": target_format,
                    "download_mode": "Batch",
                    "download_path": outdir,
                    "date": now_str()
                }
                append_history(entry)
                completed += 1
                self.ui_queue.put(("batch_item_done", completed, total_count))

            self.ui_queue.put(("batch_finished", completed, total_count))

        threading.Thread(target=batch_task, daemon=True).start()


    def on_fetch_playlist(self):
        """Fetch playlist items incrementally."""
        url = self.playlist_url_entry.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "Please enter a playlist URL.")
            return

        self.show_spinner("Fetching playlist items...")
        self._playlist_thumb_imgs = {}
        self._playlist_row_by_vid.clear()
        self._playlist_row_order.clear()
        for w in self.playlist_scroll.winfo_children():
            w.destroy()

        def task():
            try:
                cmd = [
                    windows_quote(str(YT_DLP_EXE)),
                    "--no-warnings", "--flat-playlist", "--dump-json", url
                ]
                result = run_subprocess_safe(cmd, timeout=60)
                if result["timed_out"]:
                    raise RuntimeError("yt-dlp playlist fetch timed out.")
                if result["returncode"] != 0:
                    raise RuntimeError(result["stderr"])
                lines = [l for l in result["stdout"].splitlines() if l.strip()]
                index = 0
                seen_ids = set()
                for line in lines:
                    try:
                        data = json.loads(line)
                        title = data.get("title") or "<No title>"
                        vid_id = data.get("id") or data.get("url")
                        if not vid_id or vid_id in seen_ids:
                            continue
                        seen_ids.add(vid_id)
                        full_url = f"https://youtube.com/watch?v={vid_id}"
                        entry = {"title": title, "url": full_url, "id": vid_id}
                        index += 1
                        self.ui_queue.put(("playlist_item_add", index, entry))
                    except Exception:
                        continue
                self.ui_queue.put(("playlist_fetch_done", index))
            except Exception as e:
                log_message(f"Playlist fetch error: {e}")
                self.ui_queue.put(("playlist_error", str(e)))


        if getattr(self, "_executor", None):
            self.get_executor().submit(task)
        else:
            threading.Thread(target=task, daemon=True).start()



    def on_download_playlist(self):
        import shutil
        """Download selected playlist items in order."""
        selected_entries = []
        for vid in list(self._playlist_row_order):
            row = self._playlist_row_by_vid.get(vid)
            if not row:
                continue
            try:
                sel = getattr(row, "_selected_var", None)
                if sel and sel.get():
                    entry = getattr(row, "_entry", None)
                    if entry:
                        selected_entries.append((vid, entry, row))
            except Exception:
                pass

        if not selected_entries:
            messagebox.showwarning(APP_NAME, "No playlist items selected for download. Use Select All or check items to download.")
            return

        target_format = self.playlist_format_combo.get()
        max_res = self.playlist_maxres_combo.get()
        embed_thumb = False
        outdir = self.settings.get("default_download_path", WINDOWS_DOWNLOADS_DIR)
        Path(outdir).mkdir(parents=True, exist_ok=True)
        total, used, free = shutil.disk_usage(outdir)
        if free < 500 * 1024 * 1024:
            messagebox.showwarning(APP_NAME, "Low disk space detected! You may run out during download.")
        fmt_selector = build_batch_format_selector(target_format, max_res)

        # cancel button removed; notify user via toast
        _toast(self, f"Downloading {len(selected_entries)} selected items...", title="Downloading", timeout=3000)
        self.playlist_overall_progress.set(0)
        self.current_task_cancelled = False

        cookies_path = self.settings.get("cookies_path", "") or None

        def dl_seq_task():
            total = len(selected_entries)
            completed = 0
            for vid, entry, row in selected_entries:
                if self.current_task_cancelled:
                    break
                url = entry.get("url")
                try:
                    if not hasattr(row, "_progress"):
                        row._progress = ctk.CTkProgressBar(row, width=160)
                        row._progress.grid(row=0, column=3, padx=(8,10))
                        row._progress.set(0)
                except Exception:
                    pass

                finished_event = threading.Event()
                out_path_holder = {"out": None}

                def progress_callback(percent, speed, eta, raw_line):
                    pval = (percent or 0.0) / 100.0 if percent is not None else 0.0
                    self.ui_queue.put(("playlist_row_progress", vid, pval, speed, eta))
                def finished_callback(output_path):
                    out_path_holder["out"] = output_path
                    finished_event.set()
                def error_callback(err):
                    self.ui_queue.put(("playlist_row_error", vid, str(err)))
                    finished_event.set()

                filename_template = (
                    "%(uploader)s - %(title)s.%(ext)s"
                    if self.settings.get("use_smart_naming", True)
                    else "%(title)s.%(ext)s"
                )

                self.download_proc.start_download(url, outdir, filename_template, fmt_selector, cookies_path, progress_callback, finished_callback, error_callback)

                while not finished_event.is_set():
                    if self.current_task_cancelled:
                        self.download_proc.cancel()
                        break
                    time.sleep(0.2)

                outp = out_path_holder["out"]
                if not outp:
                    try:
                        files = list(Path(outdir).glob("*"))
                        files = [f for f in files if f.is_file()]
                        if files:
                            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                            outp = str(files[0])
                    except Exception:
                        outp = None
                embedded_flag = False
                try:
                    meta = fetch_metadata_via_yt_dlp(url)
                except Exception:
                    meta = {}
                if outp and embed_thumb:
                    try:
                        thumb_url = meta.get("thumbnail")
                        if thumb_url:
                            thumbfile = TEMP_DIR / f"thumb_{int(time.time())}.jpg"
                            ok = download_thumbnail(thumb_url, str(thumbfile))
                            if ok:
                                embedded_flag = embed_thumbnail_with_ffmpeg(outp, thumbfile)
                    except Exception:
                        embedded_flag = False
                entry_hist = {
                    "title": Path(outp).stem if outp else entry.get("title",""),
                    "url": url,
                    "uploader": meta.get("uploader") if meta else "",
                    "duration": meta.get("duration_string") if meta else "",
                    "resolution": max_res,
                    "format": target_format,
                    "download_mode": "Playlist",
                    "download_path": outdir,
                    "thumbnail_embedded": bool(embedded_flag),
                    "redownloaded": False,
                    "date": now_str()
                }
                append_history(entry_hist)
                completed += 1
                self.ui_queue.put(("playlist_seq_item_done", completed, total, vid))
            self.ui_queue.put(("playlist_seq_finished", completed, len(selected_entries)))

        threading.Thread(target=dl_seq_task, daemon=True).start()

    def _playlist_row_play_preview(self, row):
        """Play preview using ffplay."""
        entry = getattr(row, "_entry", None)
        if not entry:
            return
        url = entry.get("url")
        if not url:
            return
        if not FFPLAY_EXE.exists():
            messagebox.showerror(APP_NAME, "ffplay.exe not found in Assets/. Cannot play preview.")
            return
        try:
            subprocess.Popen([str(FFPLAY_EXE), "-autoexit", "-hide_banner", "-loglevel", "error", url], shell=False)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Failed to launch preview: {e}")

    def _playlist_row_open_youtube(self, row):
        import webbrowser
        """Open video on YouTube."""
        entry = getattr(row, "_entry", None)
        if not entry:
            return
        url = entry.get("url")
        if url:
            webbrowser.open(url)

    def _playlist_row_copy_url(self, row):
        """Copy video URL to clipboard."""
        entry = getattr(row, "_entry", None)
        if not entry:
            return
        url = entry.get("url", "")
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            _toast(self, "URL copied to clipboard.")
        except Exception:
            messagebox.showinfo(APP_NAME, "Failed to copy to clipboard — please select and copy manually.")

    def _playlist_row_remove(self, row):
        """Remove row from playlist view."""
        vid = getattr(row, "_video_id", None)
        if vid and vid in self._playlist_row_by_vid:
            try:
                row.destroy()
            except Exception:
                pass
            try:
                del self._playlist_row_by_vid[vid]
            except Exception:
                pass
            self._rebuild_playlist_order()
            _toast(self, "Removed item from playlist view.")

    

    def re_download(self, entry, index_in_history=None):
        """Re-download a history entry."""
        url = entry.get("url")
        fmt = entry.get("format", self.settings.get("default_format", "mp4"))
        res = entry.get("resolution", "Best Available")
        outdir = entry.get("download_path", self.settings.get("default_download_path", WINDOWS_DOWNLOADS_DIR))
        embed = self.settings.get("embed_thumbnail", True)
        fmt_selector = build_format_selector_for_format_and_res(fmt, res)

        cookies_path = self.settings.get("cookies_path", "") or None

        def progress_callback(percent, speed, eta, rawline):
            self.ui_queue.put(("redownload_progress", percent or 0.0, speed, eta))
        def finished_callback(output_path):
            entry["redownloaded"] = True
            entry["date"] = now_str()
            append_history(entry)
            self.ui_queue.put(("redownload_finished", output_path))
            self.refresh_history()
        def error_callback(err):
            self.ui_queue.put(("redownload_error", str(err)))

        filename_template = (
            "%(uploader)s - %(title)s.%(ext)s"
            if self.settings.get("use_smart_naming", True)
            else "%(title)s.%(ext)s"
        )

        self.download_proc.start_download(url, outdir, filename_template, fmt_selector, cookies_path, progress_callback, finished_callback, error_callback)

    def safe_ui_call(self, func, *args, **kwargs):
        """Schedule a UI call on mainloop thread but guard against destroyed widgets."""
        try:
            if not getattr(self, "root", None):
                return
            def _wrapped():
                try:
                    func(*args, **kwargs)
                except Exception as e:
                    log_message(f"safe_ui_call wrapped function error: {e}")
            try:
                self.root.after(0, _wrapped)
            except Exception:
                # fallback synchronous attempt
                _wrapped()
        except Exception:
            pass

    def _reset_single_video_ui(self):
        """Reset Single Video tab UI for next download."""
        try:
            # Clear URL
            self.single_url_entry.delete(0, "end")

            # Clear metadata
            self.meta_title_var.set("")
            self.meta_uploader_var.set("")
            self.meta_duration_var.set("")

            # Reset resolution & format
            self.single_resolution_combo.configure(values=["Best Available"])
            self.single_resolution_combo.set("Best Available")

            # Reset thumbnail
            self.thumbnail_label.configure(text="Thumbnail preview", image=None)
            self.thumbnail_label.image = None
            if hasattr(self.thumbnail_label, "image_path"):
                del self.thumbnail_label.image_path

            # Disable Save Thumbnail button
            self.save_thumb_btn.configure(state="disabled", fg_color="gray")

            # Clear cached metadata
            if hasattr(self, "_last_meta"):
                del self._last_meta

            # Reset progress
            self.single_progress.set(0)
            self.single_progress_label.configure(text="")

        except Exception as e:
            log_message(f"_reset_single_video_ui error: {e}")


    


    def cancel_download(self):
        """Cancel current download."""
        self.download_proc.paused = False
        self.download_proc.last_args = None
        self.single_pause_btn.configure(state="disabled", text="Pause", command=self.pause_download)
        self.current_task_cancelled = True
        self.download_proc.cancel()
        try:
            self.single_download_btn.configure(state="normal")
        except Exception:
            pass
        _toast(self, "Download cancelled.", title="Cancelled", level="error")

    def _process_ui_queue(self):
        """Process UI update queue."""
        try:
            while True:
                item = self.ui_queue.get_nowait()
                try:
                    self._handle_ui_event(item)
                except Exception as e:
                    log_message(f"UI event error: {e}")
        except queue.Empty:
            pass
        self.root.after(100, self._process_ui_queue)

    def _handle_ui_event(self, item):
        """Handle specific UI events from queue."""
        ev = item[0]

        if ev == "meta_fetched":
            meta, sorted_res, thumb_local = item[1], item[2], item[3]
            self.fetch_meta_btn.configure(state="normal")
            self.hide_spinner()

            title = meta.get("title", "")
            uploader = meta.get("uploader", "")
            duration = meta.get("duration_string", meta.get("duration", ""))
            self.meta_title_var.set(title)
            self.meta_uploader_var.set(f"By: {uploader}")
            self.meta_duration_var.set(f"Duration: {duration}")
            self.single_resolution_combo.configure(values=sorted_res)
            self.single_resolution_combo.set(sorted_res[0] if sorted_res else "Best Available")

            # set last meta for possible thumbnail save
            self._last_meta = meta

            # thumbnail handling
            if thumb_local and os.path.exists(str(thumb_local)):
                try:
                    ctkimg = self._safe_create_ctkimage(str(thumb_local), (320, 180))
                    if ctkimg:
                        self.thumbnail_label.configure(image=ctkimg, text="")
                        self.thumbnail_label.image = ctkimg
                        # remember path for Save Thumbnail feature
                        self.thumbnail_label.image_path = str(thumb_local)
                        # enable save button
                        try:
                            self.save_thumb_btn.configure(state="normal", fg_color=SECONDARY_COLOR)
                        except Exception:
                            pass
                    else:
                        self.thumbnail_label.configure(text="Thumbnail saved")
                        self.save_thumb_btn.configure(state="normal")
                except Exception:
                    self.thumbnail_label.configure(text="Thumbnail saved")
                    try:
                        self.save_thumb_btn.configure(state="normal")
                    except Exception:
                        pass
            else:
                # attempt to fetch better thumbnail via constructed endpoints
                vid = self._extract_video_id(meta.get("webpage_url", ""))
                if vid:
                    # try common endpoints in order
                    candidates = [
                        f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
                        f"https://i.ytimg.com/vi/{vid}/sddefault.jpg",
                        f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                    ]
                    got = None
                    for c in candidates:
                        target = TEMP_DIR / f"thumb_{vid}_{Path(c).name}"
                        if download_thumbnail(c, str(target)):
                            got = str(target)
                            break
                    if got:
                        try:
                            ctkimg = self._safe_create_ctkimage(got, (320, 180))
                            if ctkimg:
                                self.thumbnail_label.configure(image=ctkimg, text="")
                                self.thumbnail_label.image = ctkimg
                                self.thumbnail_label.image_path = got
                                try:
                                    self.save_thumb_btn.configure(state="normal", fg_color=SECONDARY_COLOR)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    else:
                        self.thumbnail_label.configure(text="No thumbnail available")
                else:
                    self.thumbnail_label.configure(text="No thumbnail available")

            _toast(self, "Metadata fetched.", title="Fetch complete")
            return


        if ev == "meta_error":
            err = item[1]
            self.fetch_meta_btn.configure(state="normal")
            self.hide_spinner()
            if "age-restricted" in err.lower() or "sign in to confirm your age" in err.lower() or "members-only" in err.lower():
                messagebox.showerror(APP_NAME, "This video is age-restricted or members-only and requires sign-in. Clipster cannot download it.\n\nTip: use yt-dlp with a cookies file (manual).")
            else:
                messagebox.showerror(APP_NAME, f"Failed to fetch metadata: {err}")
            _toast(self, "Ready")
            return

        if ev == "single_progress":
            progress_value, speed, eta, raw_line = item[1], item[2], item[3], item[4]
            try:
                self.single_progress.set(progress_value)
                label = f"{int(progress_value*100)}%"
                if speed:
                    label += f" — {speed}"
                if eta:
                    label += f" — ETA {eta}"
                self.single_progress_label.configure(text=label)
            except Exception:
                pass
            return

        if ev == "single_finished":
            self.single_pause_btn.configure(text="Pause", command=self.pause_download)
            output_path, fmt, embed_thumb, url = item[1], item[2], item[3], item[4]
            if not output_path:
                outdir = self.settings.get("default_download_path", WINDOWS_DOWNLOADS_DIR)
                files = list(Path(outdir).glob("*"))
                files = [f for f in files if f.is_file()]
                if files:
                    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    output_path = str(files[0])
            embedded_flag = False
            if output_path and embed_thumb:
                try:
                    meta = fetch_metadata_via_yt_dlp(url)
                    thumb_url = meta.get("thumbnail")
                    if thumb_url:
                        thumbfile = TEMP_DIR / f"thumb_{int(time.time())}.jpg"
                        ok = download_thumbnail(thumb_url, str(thumbfile))
                        if ok:
                            embedded_flag = embed_thumbnail_with_ffmpeg(output_path, thumbfile)
                except Exception:
                    embedded_flag = False
            title = Path(output_path).stem if output_path else ""
            entry = {
                "title": title,
                "url": url,
                "uploader": "",
                "duration": "",
                "resolution": self.single_resolution_combo.get(),
                "format": fmt,
                "download_mode": "Single",
                "download_path": str(Path(output_path).parent) if output_path else self.settings.get("default_download_path", WINDOWS_DOWNLOADS_DIR),
                "thumbnail_embedded": bool(embedded_flag),
                "redownloaded": False,
                "date": now_str()
            }
            append_history(entry)
            self.single_download_btn.configure(state="normal")
            self.single_progress.set(0)
            self.single_progress_label.configure(text="")
            filename = Path(output_path).name if output_path else "File"
            windows_notify(
                "Clipster",
                f"Download finished:\n{filename}",
                open_path=output_path
            )

            self.single_pause_btn.configure(state="disabled")
            #_toast(self, f"Download finished:\n{Path(output_path).name}", title="Complete", timeout=4000)
            self.refresh_history()

            self._reset_single_video_ui()
            return

        if ev == "single_error_restricted":
            err = item[1]
            self.single_download_btn.configure(state="normal")
            self.single_progress.set(0)
            self.single_progress_label.configure(text="")
            self.hide_spinner()
            messagebox.showerror(APP_NAME, "This video requires you to be signed in (age-restricted or members-only). Clipster cannot download it without authentication.\n\nTip: use yt-dlp with a cookies file.")
            _toast(self, "Ready")
            return

        if ev == "single_error":
            err = item[1]
            self.single_download_btn.configure(state="normal")
            self.single_progress.set(0)
            self.single_progress_label.configure(text="")
            self.hide_spinner()
            messagebox.showerror(APP_NAME, f"Download failed: {err}")
            _toast(self, "Ready")
            return

        if ev == "batch_item_start":
            idx, url = item[1], item[2]
            _toast(self, f"Downloading item {idx}...", title="Downloading", timeout=2000)
            return

        if ev == "batch_item_progress":
            idx, percent, speed, eta = item[1], item[2], item[3], item[4]
            self.batch_overall_progress.set(percent or 0.0)
            return

        if ev == "batch_item_error":
            idx, err = item[1], item[2]
            messagebox.showerror(APP_NAME, f"Batch item {idx} error: {err}")
            return

        if ev == "batch_item_done":
            completed, total = item[1], item[2]
            overall = completed / total if total else 0.0
            self.batch_overall_progress.set(overall)
            _toast(self, f"Batch progress: {completed}/{total}", timeout=2200)
            self.refresh_history()
            return

        if ev == "batch_finished":
            completed, total = item[1], item[2]
            self.batch_overall_progress.set(1.0)
            windows_notify(
                "Clipster",
                f"Batch finished: {completed}/{total} downloads complete."
            )
            #_toast(self, f"Batch finished: {completed}/{total}", title="Batch", timeout=3500)
            self.refresh_history()
            return

        if ev == "playlist_item_add":
            idx, entry = item[1], item[2]
            row = ctk.CTkFrame(self.playlist_scroll, height=80)
            row.grid_columnconfigure(2, weight=1)
            sel_var = ctk.BooleanVar(value=True)
            chk = ctk.CTkCheckBox(row, text="", variable=sel_var)
            chk.grid(row=0, column=0, padx=(8,6), pady=10)
            spinner_lbl = ctk.CTkLabel(row, text="⏳", width=100, height=60, anchor="center")
            spinner_lbl.grid(row=0, column=1, padx=(6, 10), pady=6)
            title_lbl = ctk.CTkLabel(row, text=f"{idx}. {entry.get('title','<No title>')}", anchor="w", font=ctk.CTkFont(size=12))
            title_lbl.grid(row=0, column=2, sticky="w", padx=(0, 8), pady=4)
            row.pack(fill="x", padx=6, pady=4)
            row._thumb_label = spinner_lbl
            row._entry = entry
            row._video_id = entry.get("id")
            row._selected_var = sel_var
            row._checkbox = chk

            vid = entry.get("id")
            if vid:
                self._playlist_row_by_vid[vid] = row
                self._playlist_row_order.append(vid)

            def on_right_click(ev, r=row):
                items = [
                    ("▶ Play Preview", lambda rr=r: self._playlist_row_play_preview(rr)),
                    ("🌐 Open on YouTube", lambda rr=r: self._playlist_row_open_youtube(rr)),
                    ("📋 Copy URL", lambda rr=r: self._playlist_row_copy_url(rr)),
                    ("❌ Remove from list", lambda rr=r: self._playlist_row_remove(rr))
                ]
                self._show_custom_menu(ev, items)

            row.bind("<Button-3>", on_right_click)
            for child in row.winfo_children():
                child.bind("<Button-3>", on_right_click)



            try:
                self.playlist_progress_label.configure(text=f"Loaded {idx} items...")
            except Exception:
                pass

            def thumb_task(e):
                try:
                    vid = e.get("id")
                    thumb_url = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                    target = TEMP_DIR / f"pl_thumb_{vid}.jpg"
                    if not target.exists():
                        download_thumbnail(thumb_url, str(target))
                    self.ui_queue.put(("playlist_thumb_ready", vid, str(target) if target.exists() else None))
                except Exception:
                    self.ui_queue.put(("playlist_thumb_ready", e.get("id"), None))
            if getattr(self, "_executor", None):
                self.get_executor().submit(thumb_task, entry)
            else:
                threading.Thread(target=thumb_task, args=(entry,), daemon=True).start()
            return

        if ev == "playlist_fetch_done":
            total = item[1]
            self.hide_spinner()
            _toast(self, f"Fetched {total} playlist items.", title="Playlist", timeout=3000)
            try:
                self.playlist_progress_label.configure(text=f"Fetched {total} items.")
            except Exception:
                pass
            return

        if ev == "playlist_error":
            err = item[1]
            self.hide_spinner()
            messagebox.showerror(APP_NAME, f"Playlist error: {err}")
            _toast(self, "Ready")
            return

        if ev == "playlist_thumb_ready":
            vid = item[1]
            thumb_path = item[2]
            row = self._playlist_row_by_vid.get(vid)
            if row:
                lbl = getattr(row, "_thumb_label", None)
                if lbl:
                    ok = self._set_label_image_from_path(lbl, thumb_path, size=(100, 60), fallback_text="No thumb")
                    if ok:
                        try:
                            self._playlist_thumb_imgs[vid] = lbl.image
                        except Exception:
                            pass
            return

        if ev == "history_thumb_ready":
            idx = item[1]
            thumb_path = item[2]
            for child in self.history_scroll.winfo_children():
                if getattr(child, "_index", None) == idx:
                    lbl = getattr(child, "_thumb_label", None)
                    if lbl:
                        ok = self._set_label_image_from_path(lbl, thumb_path, size=(140, 80), fallback_text="No\nthumbnail")
                        if ok:
                            try:
                                self._history_thumb_imgs[idx] = lbl.image
                            except Exception:
                                pass
                    break
            return

        if ev == "redownload_progress":
            percent, speed, eta = item[1], item[2], item[3]
            try:
                self.status_var.set(f"Re-downloading... {int(percent*100)}%")
            except Exception:
                pass
            return

        if ev == "redownload_finished":
            output_path = item[1]
            filename = Path(output_path).name if output_path else "File"
            windows_notify(
                "Clipster",
                f"Re-download finished:\n{filename}",
                open_path=output_path
            )
            #_toast(self, "Re-download finished.", title="Re-Download", timeout=3000)
            #_toast(self, f"Re-download finished: {Path(output_path).name}", title="Re-Download", timeout=3500)
            self.refresh_history()
            return

        if ev == "redownload_error":
            err = item[1]
            messagebox.showerror(APP_NAME, f"Re-download error: {err}")
            return

        if ev == "playlist_row_progress":
            vid, pval, speed, eta = item[1], item[2], item[3], item[4]
            row = self._playlist_row_by_vid.get(vid)
            if row and hasattr(row, "_progress"):
                try:
                    if row._progress.winfo_exists():
                        row._progress.set(pval)
                except Exception:
                    pass


        if ev == "playlist_row_error":
            vid, err = item[1], item[2]
            row = self._playlist_row_by_vid.get(vid)
            if row:
                try:
                    if hasattr(row, "_progress"):
                        try:
                            if row._progress.winfo_exists():
                                row._progress.destroy()
                        except Exception:
                            pass
                except Exception:
                    pass
            messagebox.showerror(APP_NAME, f"Playlist item error: {err}")
            return

        if ev == "playlist_seq_item_done":
            completed, total, vid = item[1], item[2], item[3]
            overall = completed / total if total else 0.0
            self.playlist_overall_progress.set(overall)
            _toast(self, f"Playlist progress: {completed}/{total}", timeout=2200)
            row = self._playlist_row_by_vid.get(vid)
            if row:
                try:
                    if hasattr(row, "_progress"):
                        row._progress.destroy()
                except Exception:
                    pass
            self.refresh_history()
            return

        if ev == "playlist_seq_finished":
            completed, total = item[1], item[2]
            self.playlist_overall_progress.set(1.0)
            windows_notify(
                "Clipster",
                f"Playlist finished: {completed}/{total} downloads complete."
            )
            #_toast(self, f"Playlist finished: {completed}/{total}", timeout=3500)
            self.refresh_history()
            return

if __name__ == "__main__":
    try:
        ensure_directories()    
        root = ctk.CTk()
        root.withdraw()  # hide main window

        splash = SplashScreen(root)

        def start_app():
            splash.fade_out_and_destroy()  # ✨ fade-out
            app = ClipsterApp(root)

        # Keep splash visible for ~1.5 sec (or adjust)
        root.after(1500, start_app)

        root.mainloop()

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log_message(f"Unhandled exception in main: {e}\n{tb}")
        try:
            messagebox.showerror(APP_NAME, f"Fatal error during startup:\n{e}\n\nSee clipster.log for details.")
        except Exception:
            pass
        print("Fatal error during startup — see clipster.log for details.")
        print(tb)
        sys.exit(1)