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
import webbrowser
import pyperclip
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

# Set Windows AppUserModelID early so the taskbar and "open apps" panel
# show Clipster's icon instead of Python's.
def _set_app_user_model_id():
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Clipster")
    except Exception:
        pass

_set_app_user_model_id()

_HISTORY_RW_LOCK = threading.RLock()

# --------------------------------------------
# Branding / Config
# --------------------------------------------
APP_NAME = "Clipster"
APP_VERSION = "1.3.0"
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

ALLOWED_FORMATS = ["mp4", "mkv", "webm", "m4a", "mp3"]

YOUTUBE_URL_RE = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+", re.IGNORECASE)
YOUTUBE_PLAYLIST_RE = re.compile(r"(youtube\.com|youtu\.be).*[?&]list=", re.IGNORECASE)
#YOUTUBE_PLAYLIST_RE = re.compile(r"(https?://)?(www\.)?youtube\.com/.*[?&]list=", re.IGNORECASE)
YT_DLP_PROGRESS_RE = re.compile(r"\[download\]\s+([\d\.]+)%")
YT_DLP_SPEED_RE = re.compile(r"at\s+([0-9\.]+\w+/s)")
YT_DLP_ETA_RE = re.compile(r"ETA\s+([0-9:]+)")

LOG_FILE = BASE_DIR / "clipster.log"

# Module-level app reference (set in __main__) used by log_debug
_app = None

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




def truncate_text(text, max_chars=80):
    if not text:
        return ""
    text = str(text)
    return text if len(text) <= max_chars else text[:max_chars-1] + "…"



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
        settings = getattr(_app, "settings", None)
        if settings and settings.get("debug_mode"):
            log_message("[DEBUG] " + msg)
    except Exception:
        pass


def open_log_file():
    """Open the Clipster log file in the default text editor (Windows)."""
    try:
        if not LOG_FILE.exists():
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write("Clipster Log — Created automatically.\n\n")
        os.startfile(str(LOG_FILE))
    except Exception as e:
        messagebox.showerror(APP_NAME, f"Unable to open log file:\n{e}")

HISTORY_MAX_ENTRIES = 200
TEMP_FILE_MAX_AGE_DAYS = 7

def ensure_directories():
    """Ensure required directories exist and purge stale temp files."""
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    _purge_old_temp_files()

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
    "max_concurrent_downloads": 1,
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


def _purge_old_temp_files():
    """Delete temp files older than TEMP_FILE_MAX_AGE_DAYS. Best-effort, never raises."""
    try:
        cutoff = time.time() - TEMP_FILE_MAX_AGE_DAYS * 86400
        for p in TEMP_DIR.iterdir():
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


def append_history(entry):
    # Fix: Atomic read-modify-write cycle
    with _HISTORY_RW_LOCK:
        history = load_history() or []
        history.insert(0, entry)
        # Cap history to prevent unbounded growth
        if len(history) > HISTORY_MAX_ENTRIES:
            history = history[:HISTORY_MAX_ENTRIES]
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
    """Show a Windows 11 toast notification.

    open_path: if given and exists, clicking the notification opens
               that folder in Explorer. Uses win11toast's `launch`
               parameter with a file:// URI — avoids the broken
               on_click lambda behaviour that causes the
               {'arguments': 'http:', 'user_input': {}} error.
    """
    try:
        if not _is_windows():
            return

        from win11toast import toast

        kwargs = {
            "title":    title,
            "body":     message,
            "duration": "short",
            "app_id":   "Clipster.App.1.3",
        }

        # App icon in the notification badge
        icon_path = ASSETS_DIR / "clipster.png"
        if icon_path.exists():
            kwargs["icon"] = {"src": str(icon_path), "placement": "appLogoOverride"}

        # Note: Click actions removed due to win11toast API changes
        # Clicking the notification will bring the app to focus by default

        toast(**kwargs)

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
    cmd = [
        YT_DLP_EXE,
        "--no-warnings",
        "--skip-download",
        "--no-playlist",
        "--dump-single-json",
        "--no-check-certificates",
        url
    ]
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
        thread = threading.Thread(target=self._run_download, args=(url, outdir, filename_template, format_selector, cookies_path, progress_callback, finished_callback, error_callback), daemon=True)
        thread.start()
        return thread

    def _run_download(self, url, outdir, filename_template, format_selector, cookies_path, progress_callback, finished_callback, error_callback):
        """Internal method to run yt-dlp subprocess (hidden window on Windows)."""
        if not YT_DLP_EXE.exists():
            if error_callback: error_callback("yt-dlp.exe not found in Assets/")
            return
        outtmpl = os.path.join(outdir, filename_template)
        cmd = [windows_quote(str(YT_DLP_EXE)), "--no-warnings", "--newline", "--continue"]
        if cookies_path:
            cmd += ["--cookies", windows_quote(cookies_path)]
        if format_selector == "__mp3__":
            cmd += ["-o", outtmpl, "--extract-audio", "--audio-format", "mp3", "--audio-quality", "0", url]
        else:
            # Determine output format from the format selector string
            if "webm" in format_selector:
                cmd += ["-o", outtmpl, "-f", format_selector, "--merge-output-format", "webm", url]
            elif "mkv" in format_selector or format_selector == "best":
                cmd += ["-o", outtmpl, "-f", format_selector, "--merge-output-format", "mkv", url]
            else:
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
# Format selector helpers
# --------------------------------------------
def build_format_selector_for_format_and_res(target_format, resolution_label):
    """Build yt-dlp format selector string based on format and resolution."""
    height = resolution_to_height(resolution_label)
    if target_format == "mp3":
        return "__mp3__"
    if target_format == "m4a":
        return "bestaudio[ext=m4a]/bestaudio"
    if height:
        if target_format == "mp4":
            return f"bestvideo[ext=mp4][height<={height}]+bestaudio[ext=m4a]/best[height<={height}]"
        if target_format == "webm":
            return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
        if target_format == "mkv":
            return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
        return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
    else:
        if target_format == "mp4":
            return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"
        if target_format == "webm":
            return "bestvideo+bestaudio/best"
        if target_format == "mkv":
            return "bestvideo+bestaudio/best"
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

def parse_available_resolutions(formats_list, target_ext="mp4"):
    """
    Given the 'formats' list from yt-dlp JSON, return a list of resolution
    labels that are actually available, sorted best-first.
    Always includes 'Best Available'.
    For audio-only formats (mp3/m4a) returns empty list.
    """
    if not formats_list:
        return ["Best Available"]
    seen = set()
    for f in formats_list:
        h = f.get("height")
        vcodec = f.get("vcodec", "none")
        if h and vcodec and vcodec != "none":
            seen.add(h)
    heights = sorted(seen, reverse=True)
    heights = [h for h in heights if h >= 144]
    labels = ["Best Available"] + [f"{h}p" for h in heights]
    return labels if labels else ["Best Available"]


def estimate_filesize_bytes(formats_list, target_format, resolution_label):
    """
    Estimate download size in bytes for a given format + resolution.
    Sums best video stream + best audio stream sizes.
    Returns None if no size info available.
    """
    if not formats_list:
        return None
    height = resolution_to_height(resolution_label)  # None = best
    audio_only = target_format in ("mp3", "m4a")

    # Best audio stream
    audio_size = None
    best_audio_abr = -1
    for f in formats_list:
        if f.get("vcodec", "none") in (None, "none") and f.get("acodec", "none") not in (None, "none"):
            abr = f.get("abr") or 0
            sz = f.get("filesize") or f.get("filesize_approx")
            if sz and abr > best_audio_abr:
                best_audio_abr = abr
                audio_size = sz

    if audio_only:
        return audio_size

    # Best video stream at/below requested height
    video_size = None
    best_h = -1
    for f in formats_list:
        vcodec = f.get("vcodec", "none")
        if vcodec in (None, "none"):
            continue
        h = f.get("height") or 0
        if height and h > height:
            continue
        sz = f.get("filesize") or f.get("filesize_approx")
        if sz and h > best_h:
            best_h = h
            video_size = sz

    if video_size and audio_size:
        return video_size + audio_size
    return video_size or audio_size or None


def format_filesize(size_bytes):
    """Human-readable file size string."""
    if not size_bytes:
        return "?"
    if size_bytes < 1024 * 1024:
        return f"~{size_bytes / 1024:.0f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"~{size_bytes / (1024*1024):.1f} MB"
    return f"~{size_bytes / (1024*1024*1024):.2f} GB"


def build_batch_format_selector(target_format, max_resolution_label):
    """Build format selector for batch/playlist downloads."""
    if target_format == "mp3":
        return "__mp3__"
    height = resolution_to_height(max_resolution_label)
    if height:
        if target_format == "mp4":
            return f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}]"
        else:
            # For webm, mkv, and others - use generic selector, --merge-output-format will enforce container
            return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
    else:
        if target_format == "mp4":
            return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"
        # For webm, mkv, and others - use generic selector, --merge-output-format will enforce container
        return "bestvideo+bestaudio/best"

# --------------------------------------------
# GUI application (customtkinter)
# --------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class ClipsterApp:
    """Main application class for Clipster GUI."""

    def get_executor(self):
        if self._executor is None:
            import concurrent.futures
            self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=6)
        return self._executor

    def run_bg(self, func, *args):
        if getattr(self, "_executor", None):
            self.get_executor().submit(func, *args)


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

        # Set window icon — will be reinforced by _create_titlebar via WM_SETICON
        try:
            ico_path = ASSETS_DIR / "clipster.ico"
            if ico_path.exists():
                self.root.iconbitmap(default=str(ico_path))
        except Exception:
            pass

        # Hide window initially to prevent flashing during setup and to ensure
        # proper window style application before visibility
        self.root.withdraw()

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
            "Download",
            "History",
            "Settings",
            "Update",
        ):
            self.tabs.add(name)


    def _check_for_updates(self):
        """Check GitHub API for newer releases. Runs in background thread — no direct UI calls."""
        import requests
        # Signal UI that check has started
        self.ui_queue.put(("update_status", "Checking GitHub..."))
        try:
            r = requests.get(GITHUB_API_LATEST, timeout=6)
            if r.status_code != 200:
                self.ui_queue.put(("update_status", f"Failed to fetch release info ({r.status_code})"))
                return
            data = r.json()
            latest = data.get("tag_name", "").lstrip("v")
            if not latest:
                self.ui_queue.put(("update_status", "No valid release found."))
                return
            if latest == APP_VERSION:
                self.ui_queue.put(("update_status", f"✅ You’re running the latest version ({APP_VERSION})."))
            else:
                self.ui_queue.put(("update_available", latest, data))
        except Exception as e:
            self.ui_queue.put(("update_status", f"Failed to check updates: {e}"))

    def _check_update_button(self):
        threading.Thread(target=self._check_for_updates, daemon=True).start()

    def _download_and_install_update(self):
        """Download latest EXE in a background thread to avoid freezing the UI."""
        import requests
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
        self.ui_queue.put(("update_status", "Starting download..."))

        def _do_download():
            import requests
            try:
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
                                self.ui_queue.put(("update_status", f"Downloading... {percent}%"))
                self.ui_queue.put(("update_install", str(new_exe_path)))
            except Exception as e:
                self.ui_queue.put(("update_status", f"Download failed: {e}"))
                try: self.hide_spinner()
                except Exception: pass

        threading.Thread(target=_do_download, daemon=True).start()

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
                        try: self.dl_download_btn.configure(state="disabled")
                        except Exception: pass
                    except Exception:
                        pass
                    pass  # cancel btn removed in v1.3.0
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
        """Show the window with a smooth fade-in after initial setup."""
        self.root.attributes("-alpha", 0.0)
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.root.update_idletasks()
        self._fade_in_window()

    def _fade_in_window(self, alpha=0.0):
        """Incrementally increase window opacity for a fade-in effect (~200ms)."""
        alpha = min(alpha + 0.07, 1.0)
        try:
            self.root.attributes("-alpha", alpha)
        except Exception:
            return
        if alpha < 1.0:
            self.root.after(15, lambda: self._fade_in_window(alpha))

    def _create_titlebar(self):
        """Create a modern custom titlebar with Windows 11 styling."""
        import ctypes
        
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        
        # ── Apply window styles early to ensure taskbar integration ───────────────
        # This MUST happen before any UI setup and before the window becomes visible
        try:
            self._set_window_styles()
        except Exception as e:
            log_message(f"Failed to apply window styles in titlebar setup: {e}")

        # ── Set taskbar / Alt-Tab icon via WM_SETICON ─────────────────
        # This must happen early; it tells Windows which icon to show in the taskbar, 
        # the Alt+Tab switcher, and the window's own system menu.
        ico_path = ASSETS_DIR / "clipster.ico"
        try:
            if ico_path.exists():
                # Load as HICON (LR_LOADFROMFILE = 0x10, IMAGE_ICON = 1)
                ICON_SMALL = 0
                ICON_BIG   = 1
                WM_SETICON = 0x0080
                hicon_big = ctypes.windll.user32.LoadImageW(
                    None, str(ico_path), 1, 0, 0, 0x10
                )
                hicon_small = ctypes.windll.user32.LoadImageW(
                    None, str(ico_path), 1, 16, 16, 0x10
                )
                if hicon_big:
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
                if hicon_small:
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
        except Exception:
            pass

        # Also keep Tkinter's own reference so it doesn't get GC'd
        try:
            if ico_path.exists():
                self.root.iconbitmap(default=str(ico_path))
        except Exception:
            pass

        # Re-affirm AppUserModelID now that we have an HWND, ensuring the
        # taskbar groups this window under Clipster (not python.exe)
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Clipster.App.1.3")
        except Exception:
            pass

        # Rounded corners (Windows 11)
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(ctypes.c_int(2)), ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass

        # Titlebar frame — taller for breathing room
        self.titlebar_frame = ctk.CTkFrame(self.root, height=38, corner_radius=0)
        self.titlebar_frame.pack(fill="x", side="top")
        self.titlebar_frame.pack_propagate(False)
        self._update_titlebar_theme()

        # ── Left: icon + app name + version badge ──────────────────────
        left = ctk.CTkFrame(self.titlebar_frame, fg_color="transparent")
        left.pack(side="left", padx=(10, 4), pady=4)

        icon_lbl = ctk.CTkLabel(left, text="▶", font=ctk.CTkFont(size=14), width=20)
        icon_lbl.pack(side="left")

        def load_titlebar_icon():
            try:
                png_path = BASE_DIR / "Assets" / "clipster.png"
                if png_path.exists():
                    img = get_pil_image().open(png_path).convert("RGBA")
                    img.thumbnail((22, 22))
                    ctkimg = ctk.CTkImage(img, size=(22, 22))
                    icon_lbl.configure(image=ctkimg, text="")
                    icon_lbl.image = ctkimg
            except Exception:
                pass
        self.root.after(200, load_titlebar_icon)

        self._title_lbl = ctk.CTkLabel(
            left, text=APP_NAME,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self._title_lbl.pack(side="left", padx=(8, 4))

        # Version badge
        self._version_badge = ctk.CTkLabel(
            left, text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=10),
            fg_color=ACCENT_COLOR, corner_radius=4,
            width=42, height=18, text_color="white"
        )
        self._version_badge.pack(side="left", padx=(0, 8))

        self._subtitle_lbl = ctk.CTkLabel(
            left, text=SPLASH_TEXT,
            font=ctk.CTkFont(size=10), text_color="#888888"
        )
        self._subtitle_lbl.pack(side="left")

        # ── Center drag zone ───────────────────────────────────────────
        drag_zone = ctk.CTkFrame(self.titlebar_frame, fg_color="transparent")
        drag_zone.pack(side="left", fill="both", expand=True)

        for w in (drag_zone, self._title_lbl, self._subtitle_lbl, icon_lbl, self._version_badge):
            w.bind("<ButtonPress-1>", self._begin_native_drag)
            w.bind("<Double-Button-1>", lambda e: self._toggle_max_restore())

        # ── Right: window controls ─────────────────────────────────────
        btns = ctk.CTkFrame(self.titlebar_frame, fg_color="transparent")
        btns.pack(side="right", pady=4, padx=(0, 6))

        self._min_btn = ctk.CTkButton(
            btns, text="—", width=32, height=28, corner_radius=6,
            fg_color="transparent", hover_color="#3A3A3A",
            font=ctk.CTkFont(size=12),
            command=self._minimize_window
        )
        self._min_btn.pack(side="left", padx=2)

        self._max_btn = ctk.CTkButton(
            btns, text="□", width=32, height=28, corner_radius=6,
            fg_color="transparent", hover_color="#3A3A3A",
            font=ctk.CTkFont(size=12),
            command=self._toggle_max_restore
        )
        self._max_btn.pack(side="left", padx=2)

        self._close_btn = ctk.CTkButton(
            btns, text="✕", width=32, height=28, corner_radius=6,
            fg_color="transparent", hover_color="#C42B1C",
            font=ctk.CTkFont(size=12),
            command=self._close_window
        )
        self._close_btn.pack(side="left", padx=2)

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

    def _set_window_styles(self):
        """Set window styles to remove native titlebar but keep taskbar presence."""
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())

        # ── Strip native titlebar chrome ──────────────────────────────
        # Keep WS_OVERLAPPED (0x00000000 base) + WS_VISIBLE (0x10000000)
        # + WS_THICKFRAME (0x00040000) for resize + WS_SYSMENU (0x00080000)
        # WS_SYSMENU is required so Windows keeps the taskbar button.
        # Remove WS_CAPTION (0x00C00000) and WS_MINIMIZEBOX/MAXIMIZEBOX
        # so the native titlebar and its buttons disappear, but the taskbar
        # entry and icon remain.
        GWL_STYLE    = -16
        GWL_EXSTYLE  = -20
        WS_CAPTION      = 0x00C00000
        WS_BORDER       = 0x00800000
        WS_DLGFRAME     = 0x00400000
        WS_SYSMENU      = 0x00080000   # must keep — owns the taskbar button
        WS_THICKFRAME   = 0x00040000   # keep — allows resize
        WS_VISIBLE      = 0x10000000

        # Extended style: ensure WS_EX_APPWINDOW (0x00040000) is SET and
        # WS_EX_TOOLWINDOW (0x00000080) is CLEAR so the app appears in the
        # taskbar and Alt+Tab switcher.
        WS_EX_APPWINDOW  = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080

        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
        # Clear caption/border bits, keep sysmenu + thickframe + visible
        style = (style & ~(WS_CAPTION | WS_BORDER | WS_DLGFRAME)) | WS_SYSMENU | WS_THICKFRAME | WS_VISIBLE
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style)

        exstyle = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        exstyle = (exstyle & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle)

        # Apply the style change without moving/sizing the window
        SWP_NOMOVE    = 0x0002
        SWP_NOSIZE    = 0x0001
        SWP_NOZORDER  = 0x0004
        SWP_FRAMECHANGED = 0x0020
        ctypes.windll.user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED
        )

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
            self._max_btn.configure(text="⧈")
        else:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            self._is_maximized = False
            self._max_btn.configure(text="□")
        self._animate_window("show")

    def _minimize_window(self):
        """Minimize the window with animation."""
        self._animate_window("hide")
        self.root.iconify()

    def _close_window(self):
        """Close the window with a smooth fade-out effect (~150ms)."""
        self._fade_out_and_close()

    def _fade_out_and_close(self, alpha=1.0):
        """Incrementally decrease window opacity then destroy."""
        alpha = max(alpha - 0.1, 0.0)
        try:
            self.root.attributes("-alpha", alpha)
        except Exception:
            pass
        if alpha > 0.0:
            self.root.after(15, lambda: self._fade_out_and_close(alpha))
        else:
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

    
    def _path_exists(self, p):
        return Path(str(p)).exists() if p else False

    def _apply_theme(self):
        """Apply theme to the application. (override to recreate drag ghost to avoid desync)"""
        ctk.set_appearance_mode(self.settings.get("theme", "dark"))
        try:
            self.root.configure(fg_color=ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
        except Exception:
            pass
        if self._history_loaded:
            self.refresh_history()
        else:
            self.root.after(300, self.load_and_render_history)
        self._update_titlebar_theme()
        self._enable_mica_effect()
        self.root.update_idletasks()

    def _on_theme_combo_changed(self, choice):
        """Called when the user picks a new theme from the combo box — preview only, not saved."""
        # Do NOT apply or save — theme will be applied only when "Apply Settings" is clicked.
        pass


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
            self._build_download_tab(self.tabs.tab("Download"))
            self._build_history_tab(self.tabs.tab("History"))
            self._build_settings_tab(self.tabs.tab("Settings"))
            self._build_update_tab(self.tabs.tab("Update"))

            self.status_var = None
            self.cancel_btn = None
            self.spinner_overlay = None

        except Exception as e:
            log_message(f"_build_ui error: {e}")

    def _build_download_tab(self, parent):
        """Build the queue-based Download tab."""
        self._dl_queue = []
        self._dl_queue_lock = threading.Lock()

        pad = 12
        frame = ctk.CTkFrame(parent, corner_radius=12)
        frame.pack(fill="both", expand=True, padx=pad, pady=pad)

        # ── URL input row ──────────────────────────────────────────────
        url_bar = ctk.CTkFrame(frame, fg_color="transparent")
        url_bar.pack(fill="x", padx=8, pady=(10, 4))
        self.dl_url_entry = ctk.CTkEntry(
            url_bar, placeholder_text="Paste a YouTube URL and press Enter or click Add",
            height=38, corner_radius=8
        )
        self.dl_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.dl_url_entry.bind("<Return>", lambda e: self._dl_add_url())
        ctk.CTkButton(
            url_bar, text="Add", fg_color=ACCENT_COLOR,
            width=80, height=38, corner_radius=8,
            command=self._dl_add_url
        ).pack(side="left")

        # ── Queue list ─────────────────────────────────────────────────
        ctk.CTkLabel(frame, text="Download Queue:", anchor="w",
                     font=ctk.CTkFont(size=12)).pack(anchor="w", padx=10, pady=(6, 2))
        self.dl_queue_scroll = ctk.CTkScrollableFrame(frame, corner_radius=10)
        self.dl_queue_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        self._dl_empty_label = ctk.CTkLabel(
            self.dl_queue_scroll,
            text="No videos added yet. Paste a URL above to get started.",
            text_color="#888888", font=ctk.CTkFont(size=12)
        )
        self._dl_empty_label.pack(pady=40)

        # ── Overall summary bar ────────────────────────────────────────
        summary = ctk.CTkFrame(frame, corner_radius=10)
        summary.pack(fill="x", padx=8, pady=(2, 4))
        summary.grid_columnconfigure(1, weight=1)

        self.dl_overall_progress = ctk.CTkProgressBar(
            summary, height=8, corner_radius=4,
            fg_color="#2E2E2E", progress_color=ACCENT_COLOR
        )
        self.dl_overall_progress.set(0)
        self.dl_overall_progress.grid(row=0, column=0, columnspan=3, sticky="ew",
                                      padx=10, pady=(8, 4))

        self.dl_summary_lbl = ctk.CTkLabel(
            summary, text="No videos queued",
            font=ctk.CTkFont(size=11), text_color="#888888", anchor="w"
        )
        self.dl_summary_lbl.grid(row=1, column=0, sticky="w", padx=(10, 0), pady=(0, 6))

        self.dl_speed_lbl = ctk.CTkLabel(
            summary, text="",
            font=ctk.CTkFont(size=11), text_color="#aaaaaa", anchor="e"
        )
        self.dl_speed_lbl.grid(row=1, column=2, sticky="e", padx=(0, 10), pady=(0, 6))

        # ── Bottom controls row ────────────────────────────────────────
        ctrl = ctk.CTkFrame(frame, corner_radius=10)
        ctrl.pack(fill="x", padx=8, pady=(0, 8))

        ctk.CTkButton(
            ctrl, text="Clear All", fg_color="gray",
            width=90, height=34, corner_radius=8,
            command=self._dl_clear_all
        ).pack(side="right", padx=(4, 10))
        self.dl_download_btn = ctk.CTkButton(
            ctrl, text="⏬  Download All", fg_color=ACCENT_COLOR,
            width=140, height=34, corner_radius=8,
            command=self._dl_start_all
        )
        self.dl_download_btn.pack(side="right", padx=4)


    # ──────────────────────────────────────────────────────────────
    # Download Queue Methods
    # ──────────────────────────────────────────────────────────────

    def _dl_add_url(self):
        url = self.dl_url_entry.get().strip()
        if not url:
            return

        if YOUTUBE_PLAYLIST_RE.match(url):
            # Show inline playlist panel in the Download tab
            self.dl_url_entry.delete(0, "end")
            self._dl_show_playlist_panel(url)
            return

        if not YOUTUBE_URL_RE.match(url):
            _toast(self, "Not a valid YouTube URL.", level="error")
            return

        self.dl_url_entry.delete(0, "end")

        default_fmt = self.settings.get("default_format", "mp4")

        entry = {
            "url":    url,
            "title":  url,
            "uploader": "",
            "duration": "",
            "status": "fetching",
            "row":    None,
            "available_resolutions": ["Best Available"],
            "selected_res": "Best Available",
            "selected_fmt": default_fmt,
            "fmt_selector": build_format_selector_for_format_and_res(default_fmt, "Best Available"),
            "filesize_bytes": None,
            "formats_raw":    [],
            # widget refs for in-place updates (no full re-render during download)
            "_status_lbl":   None,
            "_progress_bar": None,
            "_speed_lbl":    None,
            "_size_lbl":     None,
        }

        with self._dl_queue_lock:
            idx = len(self._dl_queue)
            self._dl_queue.append(entry)

        self._dl_render_queue()
        self._dl_update_summary()
        self._dl_start_fetch_animation()

        def fetch_task(queue_idx, e):
            try:
                meta = fetch_metadata_via_yt_dlp(e["url"])
                e["title"]       = meta.get("title", e["url"])
                e["uploader"]    = meta.get("uploader", "")
                e["duration"]    = meta.get("duration_string", "")
                e["formats_raw"] = meta.get("formats", [])
                e["available_resolutions"] = parse_available_resolutions(e["formats_raw"])
                if e["selected_res"] not in e["available_resolutions"]:
                    e["selected_res"] = "Best Available"
                e["filesize_bytes"] = estimate_filesize_bytes(
                    e["formats_raw"], e["selected_fmt"], e["selected_res"]
                )
                e["fmt_selector"] = build_format_selector_for_format_and_res(
                    e["selected_fmt"], e["selected_res"]
                )
                self.ui_queue.put(("dl_meta_ready", queue_idx))
            except Exception as ex:
                self.ui_queue.put(("dl_item_status", queue_idx, "error", str(ex)))

        threading.Thread(target=fetch_task, args=(idx, entry), daemon=True).start()

    # ──────────────────────────────────────────────────────────────
    # Inline Playlist Panel (shown inside Download tab)
    # ──────────────────────────────────────────────────────────────

    def _dl_show_playlist_panel(self, url):
        """Show an inline playlist fetcher panel inside the Download tab queue area."""
        # Clear previous panel if any
        self._dl_dismiss_playlist_panel()

        self._pl_panel = ctk.CTkFrame(self.dl_queue_scroll, corner_radius=10)
        self._pl_panel.pack(fill="x", padx=4, pady=(4, 8))

        # Header row
        hdr = ctk.CTkFrame(self._pl_panel, fg_color="transparent")
        hdr.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(hdr, text="📋 Playlist Downloader", font=ctk.CTkFont(size=13, weight="bold"), anchor="w").pack(side="left")
        ctk.CTkButton(hdr, text="✕ Close", fg_color="gray", width=80, height=28, corner_radius=6,
                      command=self._dl_dismiss_playlist_panel).pack(side="right")

        # URL display
        url_row = ctk.CTkFrame(self._pl_panel, fg_color="transparent")
        url_row.pack(fill="x", padx=8, pady=(0, 4))
        self._pl_url_entry = ctk.CTkEntry(url_row, height=34, corner_radius=8)
        self._pl_url_entry.insert(0, url)
        self._pl_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(url_row, text="Fetch Items", fg_color=ACCENT_COLOR, height=34, corner_radius=8,
                      width=110, command=self._pl_fetch_items).pack(side="left")

        # Progress label
        self._pl_status_lbl = ctk.CTkLabel(self._pl_panel, text="", anchor="w", font=ctk.CTkFont(size=11))
        self._pl_status_lbl.pack(anchor="w", padx=10, pady=(2, 0))

        # Scrollable video list
        self._pl_items_frame = ctk.CTkScrollableFrame(self._pl_panel, height=200, corner_radius=8)
        self._pl_items_frame.pack(fill="both", expand=True, padx=8, pady=(4, 6))

        # Bottom controls
        bottom = ctk.CTkFrame(self._pl_panel, fg_color="transparent")
        bottom.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkLabel(bottom, text="Format:").pack(side="left", padx=(0, 4))
        self._pl_format_combo = ctk.CTkComboBox(bottom, values=ALLOWED_FORMATS, width=100, height=32, corner_radius=8)
        self._pl_format_combo.set(self.settings.get("default_format", "mp4"))
        self._pl_format_combo.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(bottom, text="Max Res:").pack(side="left", padx=(0, 4))
        self._pl_res_combo = ctk.CTkComboBox(bottom, values=["Best Available", "1080p", "720p", "480p"], width=130, height=32, corner_radius=8)
        self._pl_res_combo.set("Best Available")
        self._pl_res_combo.pack(side="left", padx=(0, 10))
        ctk.CTkButton(bottom, text="Select All", fg_color="gray", width=90, height=32, corner_radius=8,
                      command=self._pl_select_all).pack(side="left", padx=4)
        ctk.CTkButton(bottom, text="Deselect All", fg_color="gray", width=90, height=32, corner_radius=8,
                      command=self._pl_deselect_all).pack(side="left", padx=4)
        ctk.CTkButton(bottom, text="⏬ Add to Queue", fg_color=ACCENT_COLOR, width=130, height=32, corner_radius=8,
                      command=self._pl_add_selected_to_queue).pack(side="right", padx=4)

        self._pl_rows = []  # list of (BoolVar, entry_dict)
        self._pl_empty_lbl = ctk.CTkLabel(self._pl_items_frame, text="Press 'Fetch Items' to load playlist videos.",
                                          text_color="#888888", font=ctk.CTkFont(size=12))
        self._pl_empty_lbl.pack(pady=20)

        # Kick off fetch automatically
        self.root.after(100, self._pl_fetch_items)

    def _dl_dismiss_playlist_panel(self):
        """Remove the inline playlist panel if it exists."""
        panel = getattr(self, "_pl_panel", None)
        if panel:
            try:
                panel.destroy()
            except Exception:
                pass
            self._pl_panel = None
            self._pl_rows = []

    def _pl_fetch_items(self):
        """Fetch playlist items and populate the inline panel."""
        url = getattr(self, "_pl_url_entry", None)
        if not url:
            return
        url = self._pl_url_entry.get().strip()
        if not url:
            return

        # Clear existing rows
        self._pl_rows = []
        for w in self._pl_items_frame.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        self._pl_status_lbl.configure(text="⏳ Fetching playlist items...")

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
                    raise RuntimeError(result["stderr"] or "yt-dlp returned error")
                lines = [l for l in result["stdout"].splitlines() if l.strip()]
                seen_ids = set()
                items = []
                for line in lines:
                    try:
                        data = json.loads(line)
                        vid_id = data.get("id") or data.get("url")
                        if not vid_id or vid_id in seen_ids:
                            continue
                        seen_ids.add(vid_id)
                        title = data.get("title") or "<No title>"
                        full_url = f"https://youtube.com/watch?v={vid_id}"
                        items.append({"title": title, "url": full_url, "id": vid_id})
                    except Exception:
                        continue
                self.ui_queue.put(("pl_inline_items_ready", items))
            except Exception as e:
                self.ui_queue.put(("pl_inline_error", str(e)))

        threading.Thread(target=task, daemon=True).start()

    def _pl_render_items(self, items):
        """Render fetched playlist items into the inline panel."""
        # Clear
        for w in self._pl_items_frame.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self._pl_rows = []

        if not items:
            ctk.CTkLabel(self._pl_items_frame, text="No items found in this playlist.",
                         text_color="#888888").pack(pady=20)
            return

        for i, entry in enumerate(items):
            var = ctk.BooleanVar(value=True)
            row = ctk.CTkFrame(self._pl_items_frame, fg_color="transparent", height=32)
            row.pack(fill="x", padx=4, pady=2)
            chk = ctk.CTkCheckBox(row, text="", variable=var, width=28)
            chk.pack(side="left", padx=(4, 6))
            lbl = ctk.CTkLabel(row, text=f"{i+1}. {entry['title']}", anchor="w",
                               font=ctk.CTkFont(size=11))
            lbl.pack(side="left", fill="x", expand=True)
            self._pl_rows.append((var, entry))

        self._pl_status_lbl.configure(text=f"✅ {len(items)} items loaded. Select items and click 'Add to Queue'.")

    def _pl_select_all(self):
        for var, _ in self._pl_rows:
            var.set(True)

    def _pl_deselect_all(self):
        for var, _ in self._pl_rows:
            var.set(False)

    def _pl_add_selected_to_queue(self):
        """Add selected playlist items to the download queue as individual entries."""
        selected = [(var, e) for var, e in self._pl_rows if var.get()]
        if not selected:
            _toast(self, "No items selected.", level="error")
            return

        fmt = self._pl_format_combo.get()
        res = self._pl_res_combo.get()
        fmt_selector = build_batch_format_selector(fmt, res)

        added = 0
        for _, entry in selected:
            q_entry = {
                "url":    entry["url"],
                "title":  entry["title"],
                "uploader": "",
                "duration": "",
                "status": "ready",
                "row":    None,
                "available_resolutions": [res],
                "selected_res": res,
                "selected_fmt": fmt,
                "fmt_selector": fmt_selector,
                "filesize_bytes": None,
                "formats_raw": [],
                "_status_lbl":   None,
                "_progress_bar": None,
                "_speed_lbl":    None,
                "_size_lbl":     None,
                "_progress_pct": 0.0,
                "_speed_text":   "",
            }
            with self._dl_queue_lock:
                self._dl_queue.append(q_entry)
            added += 1

        self._dl_render_queue()
        self._dl_update_summary()
        self._dl_dismiss_playlist_panel()
        _toast(self, f"Added {added} playlist items to queue.", title="Playlist")

    def _dl_update_summary(self):
        """Recompute and refresh the overall progress bar + summary label."""
        try:
            with self._dl_queue_lock:
                items = list(self._dl_queue)

            if not items:
                self.dl_overall_progress.set(0)
                self.dl_summary_lbl.configure(text="No videos queued")
                self.dl_speed_lbl.configure(text="")
                return

            total   = len(items)
            done    = sum(1 for e in items if e.get("status") == "done")
            errors  = sum(1 for e in items if e.get("status") == "error")
            active  = [e for e in items if e.get("status") == "downloading"]

            # Overall progress fraction
            # Each item contributes 1.0 when done, or its current _progress_pct when downloading
            progress_sum = done
            for e in active:
                progress_sum += e.get("_progress_pct", 0.0)
            overall = progress_sum / total if total else 0.0
            self.dl_overall_progress.set(min(overall, 1.0))

            # Total size across all items that have size info
            total_bytes = 0
            known_size_count = 0
            for e in items:
                sz = e.get("filesize_bytes")
                if sz:
                    total_bytes += sz
                    known_size_count += 1

            # Build summary text
            status_parts = []
            if done:
                status_parts.append(f"✅ {done} done")
            if active:
                status_parts.append(f"⬇ {len(active)} downloading")
            if errors:
                status_parts.append(f"✖ {errors} failed")
            fetching = sum(1 for e in items if e.get("status") == "fetching")
            ready    = sum(1 for e in items if e.get("status") == "ready")
            if fetching:
                status_parts.append(f"⏳ {fetching} fetching")
            if ready:
                status_parts.append(f"✔ {ready} ready")

            size_str = ""
            if known_size_count > 0:
                size_str = f"  •  {format_filesize(total_bytes)} total"
                if known_size_count < total:
                    size_str += f" ({known_size_count}/{total} known)"

            summary_text = "  ·  ".join(status_parts) + size_str if status_parts else f"{total} video(s) queued"
            self.dl_summary_lbl.configure(text=summary_text)

        except Exception as e:
            log_message(f"_dl_update_summary error: {e}")

    def _dl_render_queue(self):
        """Full rebuild of queue rows. Only called on structural changes
        (add / remove / status flip). NOT called during download progress."""
        try:
            for w in self.dl_queue_scroll.winfo_children():
                w.destroy()

            with self._dl_queue_lock:
                items = list(self._dl_queue)

            if not items:
                lbl = ctk.CTkLabel(
                    self.dl_queue_scroll,
                    text="No videos added yet. Paste a URL above to get started.",
                    text_color="#888888", font=ctk.CTkFont(size=12)
                )
                lbl.pack(pady=40)
                self._dl_empty_label = lbl
                return

            for i, entry in enumerate(items):
                self._dl_build_row(i, entry)

            if any(e.get("status") == "fetching" for e in items):
                self._dl_start_fetch_animation()

        except Exception as e:
            log_message(f"_dl_render_queue error: {e}")

    def _dl_build_row(self, i, entry):
        """Build a single queue row and store widget refs on the entry dict."""
        status   = entry.get("status", "pending")
        is_audio = entry.get("selected_fmt", "mp4") in ("mp3", "m4a")
        is_downloading = status == "downloading"

        row = ctk.CTkFrame(self.dl_queue_scroll, corner_radius=8)
        row.pack(fill="x", padx=4, pady=3)
        row.grid_columnconfigure(1, weight=1)

        # ── Line 1: badge  title  remove ──────────────────────────────
        badge_color, badge_text = {
            "pending":     ("#444444", "⏺ Pending"),
            "fetching":    ("#555555", "⏳ Fetching"),
            "ready":       ("#1a7a3f", "✔ Ready"),
            "downloading": (ACCENT_COLOR, "⬇ Downloading"),
            "done":        ("#1a7a3f", "✅ Done"),
            "error":       ("#b22222", "✖ Error"),
        }.get(status, ("#555555", status))

        status_lbl = ctk.CTkLabel(
            row, text=badge_text, width=110, height=24,
            fg_color=badge_color, corner_radius=6,
            font=ctk.CTkFont(size=11)
        )
        status_lbl.grid(row=0, column=0, padx=(8, 6), pady=(8, 2), sticky="w")
        entry["_status_lbl"] = status_lbl

        title_text = truncate_text(entry.get("title", entry["url"]), 75)
        if status == "error":
            title_text = f"✖ {entry.get('error', 'Failed')}"
        title_lbl = ctk.CTkLabel(
            row, text=title_text, anchor="w",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        title_lbl.grid(row=0, column=1, sticky="w", padx=(0, 4), pady=(8, 2))
        entry["_title_lbl"] = title_lbl

        def make_remove(idx=i):
            return lambda: self._dl_remove_item(idx)
        ctk.CTkButton(
            row, text="✕", width=26, height=26,
            fg_color="transparent", hover_color="#8B0000",
            corner_radius=6, font=ctk.CTkFont(size=12),
            command=make_remove()
        ).grid(row=0, column=2, padx=(0, 8), pady=(8, 2))

        # ── Line 2: meta  res-combo  size ─────────────────────────────
        meta_frame = ctk.CTkFrame(row, fg_color="transparent")
        meta_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=(8, 8), pady=(0, 4))

        uploader = entry.get("uploader", "")
        duration = entry.get("duration", "")
        meta_parts = [p for p in [uploader, duration] if p]
        meta_str = "  ·  ".join(meta_parts) if meta_parts else (
            "Fetching info..." if status == "fetching" else "")
        if meta_str:
            ctk.CTkLabel(
                meta_frame, text=meta_str, anchor="w",
                font=ctk.CTkFont(size=11), text_color="#888888"
            ).pack(side="left", padx=(0, 10))

        # Resolution combo — only for video formats, only when not done/error
        if not is_audio and status not in ("done", "error"):
            avail_res = entry.get("available_resolutions", ["Best Available"])
            res_combo = ctk.CTkComboBox(
                meta_frame,
                values=avail_res,
                width=130, height=26, corner_radius=6,
                font=ctk.CTkFont(size=11),
                state="normal" if status == "ready" else "disabled"
            )
            res_combo.set(entry.get("selected_res", "Best Available"))
            res_combo.pack(side="left", padx=(0, 8))

            sz_text = format_filesize(entry.get("filesize_bytes")) if status == "ready" else ""
            size_lbl = ctk.CTkLabel(
                meta_frame, text=sz_text,
                font=ctk.CTkFont(size=11), text_color="#aaaaaa", width=80, anchor="w"
            )
            size_lbl.pack(side="left")
            entry["_size_lbl"] = size_lbl

            def on_res_change(choice, e=entry, lbl=size_lbl):
                e["selected_res"] = choice
                e["fmt_selector"] = build_format_selector_for_format_and_res(
                    e["selected_fmt"], choice)
                e["filesize_bytes"] = estimate_filesize_bytes(
                    e.get("formats_raw", []), e["selected_fmt"], choice)
                lbl.configure(text=format_filesize(e["filesize_bytes"]))
                self._dl_update_summary()

            res_combo.configure(command=on_res_change)

        elif is_audio and status == "ready":
            size_lbl = ctk.CTkLabel(
                meta_frame, text=format_filesize(entry.get("filesize_bytes")),
                font=ctk.CTkFont(size=11), text_color="#aaaaaa"
            )
            size_lbl.pack(side="left")
            entry["_size_lbl"] = size_lbl

        # ── Line 3: per-item progress bar + speed/ETA (only while downloading) ──
        if is_downloading:
            prog_frame = ctk.CTkFrame(row, fg_color="transparent")
            prog_frame.grid(row=2, column=0, columnspan=3, sticky="ew",
                            padx=(8, 8), pady=(0, 8))

            pbar = ctk.CTkProgressBar(
                prog_frame, height=6, corner_radius=3,
                fg_color="#2E2E2E", progress_color=ACCENT_COLOR
            )
            pbar.set(entry.get("_progress_pct", 0.0))
            pbar.pack(side="left", fill="x", expand=True, padx=(0, 8))
            entry["_progress_bar"] = pbar

            speed_lbl = ctk.CTkLabel(
                prog_frame, text=entry.get("_speed_text", ""),
                font=ctk.CTkFont(size=10), text_color="#aaaaaa", width=120, anchor="e"
            )
            speed_lbl.pack(side="right")
            entry["_speed_lbl"] = speed_lbl
        else:
            entry["_progress_bar"] = None
            entry["_speed_lbl"]    = None

        entry["row"] = row
        row._dl_entry = entry

    def _dl_start_fetch_animation(self):
        """Pulse the status badge of fetching rows. Uses stored _status_lbl refs — no DOM walk."""
        if getattr(self, "_fetch_anim_running", False):
            return
        self._fetch_anim_running = True
        self._fetch_anim_dots = 0

        def tick():
            with self._dl_queue_lock:
                fetching = [e for e in self._dl_queue if e.get("status") == "fetching"]
            if not fetching:
                self._fetch_anim_running = False
                return
            self._fetch_anim_dots = (self._fetch_anim_dots + 1) % 4
            dots = "." * self._fetch_anim_dots
            for e in fetching:
                lbl = e.get("_status_lbl")
                if lbl:
                    try:
                        if lbl.winfo_exists():
                            lbl.configure(text=f"⏳ Fetching{dots}")
                    except Exception:
                        pass
            self.root.after(500, tick)

        self.root.after(500, tick)

    def _dl_remove_item(self, idx):
        """Remove item at idx from queue and re-render."""
        with self._dl_queue_lock:
            if 0 <= idx < len(self._dl_queue):
                self._dl_queue.pop(idx)
        self._dl_render_queue()
        self._dl_update_summary()

    def _dl_clear_all(self):
        """Clear the entire queue."""
        with self._dl_queue_lock:
            self._dl_queue.clear()
        self._dl_render_queue()
        self._dl_update_summary()

    def _dl_start_all(self):
        import shutil

        with self._dl_queue_lock:
            items = [(i, e) for i, e in enumerate(self._dl_queue)
                     if e.get("status") in ("ready", "error")]

        if not items:
            with self._dl_queue_lock:
                still_fetching = any(e.get("status") == "fetching" for e in self._dl_queue)
            if still_fetching:
                _toast(self, "Still fetching video info, please wait...", level="info")
            else:
                _toast(self, "No items ready to download.", level="error")
            return

        outdir = self.settings.get("default_download_path", WINDOWS_DOWNLOADS_DIR)
        Path(outdir).mkdir(parents=True, exist_ok=True)

        global_fmt      = self.settings.get("default_format", "mp4")
        global_selector = build_format_selector_for_format_and_res(global_fmt, "Best Available")

        cookies_path = self.settings.get("cookies_path", "") or None
        filename_template = (
            "%(uploader)s - %(title)s.%(ext)s"
            if self.settings.get("use_smart_naming", True)
            else "%(title)s.%(ext)s"
        )

        self.dl_download_btn.configure(state="disabled")
        total_count = len(items)

        def dl_task():
            completed = 0
            for queue_idx, entry in items:
                fmt_selector = entry.get("fmt_selector") or global_selector

                # Flip status → downloading (triggers full row rebuild with progress bar)
                self.ui_queue.put(("dl_item_status", queue_idx, "downloading", ""))

                finished_event = threading.Event()
                result = {"path": None, "error": None}

                def progress_cb(percent, speed, eta, raw, _qidx=queue_idx, _entry=entry):
                    pval = (percent or 0.0) / 100.0
                    _entry["_progress_pct"] = pval
                    speed_text = ""
                    if speed:
                        speed_text = speed
                    if eta:
                        speed_text += f"  ETA {eta}"
                    _entry["_speed_text"] = speed_text
                    self.ui_queue.put(("dl_item_progress", _qidx, pval, speed_text))

                def finished_cb(path, _r=result, _ev=finished_event):
                    _r["path"] = path
                    _ev.set()

                def error_cb(err, _r=result, _ev=finished_event):
                    _r["error"] = err
                    _ev.set()

                self.download_proc.start_download(
                    entry["url"], outdir, filename_template,
                    fmt_selector, cookies_path,
                    progress_cb, finished_cb, error_cb
                )

                while not finished_event.is_set():
                    time.sleep(0.25)

                if result["error"]:
                    entry["_progress_pct"] = 0.0
                    self.ui_queue.put(("dl_item_status", queue_idx, "error", result["error"]))
                else:
                    completed += 1
                    entry["_progress_pct"] = 1.0
                    append_history({
                        "url":           entry["url"],
                        "title":         entry.get("title", ""),
                        "uploader":      entry.get("uploader", ""),
                        "format":        entry.get("selected_fmt", global_fmt),
                        "resolution":    entry.get("selected_res", "Best Available"),
                        "download_path": outdir,
                        "date":          now_str(),
                    })
                    self.ui_queue.put(("dl_item_status", queue_idx, "done", ""))

            self.ui_queue.put(("dl_all_finished", completed, total_count))

        threading.Thread(target=dl_task, daemon=True).start()


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

        # Top controls: Search and buttons
        top = ctk.CTkFrame(frame, corner_radius=10)
        top.pack(fill="x", pady=(0, 8))

        # Search bar
        search_frame = ctk.CTkFrame(top, fg_color="transparent")
        search_frame.pack(side="left", fill="x", expand=True, padx=(6, 8), pady=6)
        self.history_search_entry = ctk.CTkEntry(
            search_frame, placeholder_text="Search history...",
            height=36, corner_radius=8
        )
        self.history_search_entry.pack(fill="x", expand=True)
        self.history_search_entry.bind("<KeyRelease>", self._on_history_search)

        # Buttons
        btn_frame = ctk.CTkFrame(top, fg_color="transparent")
        btn_frame.pack(side="right", padx=(0, 6), pady=6)
        ctk.CTkButton(
            btn_frame,
            text="⟳  Refresh",
            command=self.refresh_history,
            fg_color=SECONDARY_COLOR,
            hover_color="#009aA8",
            height=34,
            width=110,
            corner_radius=8,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_frame,
            text="🗑  Clear All",
            command=self.clear_history_prompt,
            fg_color="#C0392B",
            hover_color="#96281B",
            height=34,
            width=110,
            corner_radius=8,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left")

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
        self.history = load_history()
        search_term = self.history_search_entry.get().strip().lower() if hasattr(self, 'history_search_entry') else ""
        filtered_history = self.history
        if search_term:
            filtered_history = [entry for entry in self.history if search_term in entry.get("title", "").lower() or search_term in entry.get("uploader", "").lower()]
        if not filtered_history:
            lbl = ctk.CTkLabel(self.history_scroll, text="No history yet." if not search_term else "No matches found.", anchor="center")
            lbl.pack(pady=12)
            return

        for idx, entry in enumerate(filtered_history):
            row = self._create_history_row(idx, entry)
            row.pack(fill="x", pady=6, padx=6)



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

        title = entry.get("title", "<No title>")
        uploader = entry.get("uploader", "")
        fmt = entry.get("format", "").upper()
        res = entry.get("resolution", "")
        date = entry.get("date", "")
        # For audio-only formats, skip the redundant resolution field
        if fmt in ("MP3", "M4A") or res == "N/A (Audio Only)":
            info_text = f"{uploader} • {fmt} • {date}"
        else:
            info_text = f"{uploader} • {fmt} {res} • {date}"
        row_frame.grid_columnconfigure(0, weight=1)
        title_lbl = ctk.CTkLabel(row_frame, text=title, anchor="w", font=ctk.CTkFont(size=13, weight="bold"))
        title_lbl.grid(row=0, column=0, sticky="w", padx=(10,8), pady=(8,0))
        info_lbl = ctk.CTkLabel(row_frame, text=info_text, anchor="w", font=ctk.CTkFont(size=10))
        info_lbl.grid(row=1, column=0, sticky="w", padx=(10,8), pady=(0,8))

        # Buttons
        theme = self.settings.get("theme", "dark")
        hover_color = "#e0e0e0" if theme == "light" else "#3A3A3A"
        btn_bg = "#2B2B2B" if theme == "dark" else "#E8E8E8"
        btns = ctk.CTkFrame(row_frame, fg_color="transparent")
        btns.grid(row=0, column=1, rowspan=2, padx=(4, 10), pady=4)

        # Open in browser button
        open_btn = ctk.CTkButton(
            btns, text="🌐  Open",
            width=72, height=30, corner_radius=6,
            fg_color="#1E6B3C", hover_color="#175430",
            font=ctk.CTkFont(size=11),
            command=lambda: self._history_open_in_browser(entry),
        )
        open_btn.pack(side="left", padx=(0, 4))

        # Copy URL button
        copy_btn = ctk.CTkButton(
            btns, text="📋  Copy URL",
            width=90, height=30, corner_radius=6,
            fg_color="#6B3FA0", hover_color="#552F80",
            font=ctk.CTkFont(size=11),
            command=lambda: self._history_copy_url(entry),
        )
        copy_btn.pack(side="left", padx=(0, 4))

        # Delete button
        del_btn = ctk.CTkButton(
            btns, text="✕",
            width=30, height=30, corner_radius=6,
            fg_color="transparent", hover_color="#C0392B",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#E74C3C",
            command=lambda: self._delete_history_entry(idx),
        )
        del_btn.pack(side="left")

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

    def _on_history_search(self, event=None):
        """Handle search input change."""
        self.refresh_history()

    def clear_history_prompt(self):
        """Prompt to clear history."""
        if messagebox.askyesno(APP_NAME, "Clear entire download history?"):
            clear_history()
            self.refresh_history()

    def _history_open_in_browser(self, entry):
        """Open the video URL in the default web browser."""
        url = entry.get("url", "")
        if url:
            webbrowser.open(url)

    def _history_copy_url(self, entry):
        """Copy the video URL to clipboard."""
        url = entry.get("url", "")
        if url:
            pyperclip.copy(url)
            _toast(self, "URL copied to clipboard")

    def _delete_history_entry(self, idx):
        """Delete a history entry."""
        delete_history_entry(idx)
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
        btn_frame.pack(pady=14)

        self.update_check_btn = ctk.CTkButton(
            btn_frame,
            text="⟳  Recheck",
            fg_color=ACCENT_COLOR,
            hover_color="#005fa3",
            height=36,
            width=130,
            corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._check_update_button,
        )
        self.update_check_btn.pack(side="left", padx=6)

        self.update_download_btn = ctk.CTkButton(
            btn_frame,
            text="⬇️  Download & Install",
            fg_color=SECONDARY_COLOR,
            hover_color="#009aA8",
            height=36,
            width=180,
            corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._download_and_install_update,
        )
        self.update_download_btn.pack(side="left", padx=6)

        self.update_open_btn = ctk.CTkButton(
            btn_frame,
            text="🌐  GitHub Releases",
            fg_color="#555555",
            hover_color="#404040",
            height=36,
            width=155,
            corner_radius=8,
            font=ctk.CTkFont(size=13),
            command=lambda: webbrowser.open(GITHUB_RELEASES_URL),
        )
        self.update_open_btn.pack(side="left", padx=6)

        # Check for updates on load
        threading.Thread(target=self._check_for_updates, daemon=True).start()


    # ──────────────────────────────────────────────────────────────
    #  SETTINGS TAB
    # ──────────────────────────────────────────────────────────────
    def _build_settings_tab(self, parent):
        """Build UI for Settings tab."""
        frame = ctk.CTkScrollableFrame(parent, corner_radius=12)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        def section_label(text):
            ctk.CTkLabel(frame, text=text, anchor="w",
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=ACCENT_COLOR).pack(fill="x", padx=8, pady=(16, 2))

        def row_frame():
            f = ctk.CTkFrame(frame, fg_color="transparent")
            f.pack(fill="x", padx=8, pady=(4, 2))
            return f

        # ── Appearance ──────────────────────────────────────────────
        section_label("🎨  Appearance")

        tf = row_frame()
        ctk.CTkLabel(tf, text="Theme:", anchor="w", width=160).pack(side="left", padx=(0, 8))
        self.settings_theme_combo = ctk.CTkComboBox(tf, values=["dark", "light", "system"], width=150,
                                                    height=36, corner_radius=8,
                                                    command=self._on_theme_combo_changed)
        self.settings_theme_combo.set(self.settings.get("theme", "dark"))
        self.settings_theme_combo.pack(side="left")
        ctk.CTkLabel(tf, text="(applies on Save)", text_color="#888888",
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(8, 0))

        # ── Downloads ───────────────────────────────────────────────
        section_label("⬇️  Downloads")

        ff = row_frame()
        ctk.CTkLabel(ff, text="Default format:", anchor="w", width=160).pack(side="left", padx=(0, 8))
        self.settings_format_combo = ctk.CTkComboBox(ff, values=ALLOWED_FORMATS, width=150, height=36, corner_radius=8)
        self.settings_format_combo.set(self.settings.get("default_format", "mp4"))
        self.settings_format_combo.pack(side="left")

        pf = row_frame()
        ctk.CTkLabel(pf, text="Download folder:", anchor="w", width=160).pack(side="left", padx=(0, 8))
        self.default_download_path_entry = ctk.CTkEntry(pf, width=360, height=36, corner_radius=8)
        self.default_download_path_entry.insert(0, self.settings.get("default_download_path", str(DOWNLOADS_DIR)))
        self.default_download_path_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(pf, text="Browse", height=36, corner_radius=8,
                      command=self.on_choose_download_folder).pack(side="left")

        # Max concurrent downloads
        concf = row_frame()
        ctk.CTkLabel(concf, text="Max concurrent downloads:", anchor="w", width=160).pack(side="left", padx=(0, 8))
        self.settings_max_dl_combo = ctk.CTkComboBox(concf, values=["1", "2", "3", "4", "5"],
                                                     width=80, height=36, corner_radius=8)
        self.settings_max_dl_combo.set(str(self.settings.get("max_concurrent_downloads", 1)))
        self.settings_max_dl_combo.pack(side="left")

        # ── Naming ──────────────────────────────────────────────────
        section_label("📝  Naming")

        nf = row_frame()
        ctk.CTkLabel(nf, text="Smart naming (uploader - title):", anchor="w", width=220).pack(side="left", padx=(0, 8))
        self.settings_smart_naming_switch = ctk.CTkSwitch(nf, text="")
        if self.settings.get("use_smart_naming", True):
            self.settings_smart_naming_switch.select()
        else:
            self.settings_smart_naming_switch.deselect()
        self.settings_smart_naming_switch.pack(side="left")

        # ── Cookies ─────────────────────────────────────────────────
        section_label("🍪  Authentication (Cookies)")

        cf = row_frame()
        ctk.CTkLabel(cf, text="Cookies file (.txt):", anchor="w", width=160).pack(side="left", padx=(0, 8))
        self.settings_cookies_entry = ctk.CTkEntry(cf, width=360, height=36, corner_radius=8,
                                                    placeholder_text="Optional — for age-restricted videos")
        self.settings_cookies_entry.insert(0, self.settings.get("cookies_path", ""))
        self.settings_cookies_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(cf, text="Browse", height=36, corner_radius=8,
                      command=self._on_browse_cookies).pack(side="left")

        # ── Notifications ───────────────────────────────────────────
        section_label("🔔  Notifications")

        notf = row_frame()
        ctk.CTkLabel(notf, text="Show toast notifications:", anchor="w", width=220).pack(side="left", padx=(0, 8))
        self.settings_toast_switch = ctk.CTkSwitch(notf, text="")
        if self.settings.get("show_toasts", True):
            self.settings_toast_switch.select()
        else:
            self.settings_toast_switch.deselect()
        self.settings_toast_switch.pack(side="left")

        # ── Debug ───────────────────────────────────────────────────
        section_label("🛠️  Advanced / Debug")

        df = row_frame()
        ctk.CTkLabel(df, text="Debug mode (verbose log):", anchor="w", width=220).pack(side="left", padx=(0, 8))
        self.settings_debug_switch = ctk.CTkSwitch(df, text="")
        if self.settings.get("debug_mode", False):
            self.settings_debug_switch.select()
        else:
            self.settings_debug_switch.deselect()
        self.settings_debug_switch.pack(side="left")

        lf = row_frame()
        ctk.CTkButton(lf, text="📄 Open Log File", fg_color=SECONDARY_COLOR, height=36, corner_radius=8,
                      command=open_log_file).pack(side="left", padx=(0, 8))
        ctk.CTkButton(lf, text="🗑️ Clear Log", fg_color="gray", height=36, corner_radius=8,
                      command=self._on_clear_log).pack(side="left")

        # ── Save / Reset ────────────────────────────────────────────
        ctk.CTkFrame(frame, height=1, fg_color="#333333").pack(fill="x", padx=8, pady=(16, 6))
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(anchor="nw", padx=8, pady=(0, 16))
        ctk.CTkButton(btn_frame, text="💾 Save Settings", fg_color=ACCENT_COLOR, height=36, corner_radius=8,
                      command=self.on_apply_settings).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_frame, text="↺ Reset to Defaults", fg_color="gray", height=36, corner_radius=8,
                      command=self.on_reset_defaults).pack(side="left", padx=4)

    def _on_browse_cookies(self):
        path = filedialog.askopenfilename(
            title="Select cookies file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.settings_cookies_entry.delete(0, "end")
            self.settings_cookies_entry.insert(0, path)

    def _on_clear_log(self):
        try:
            if LOG_FILE.exists():
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    f.write(f"Clipster Log — Cleared {now_str()}\n\n")
            _toast(self, "Log file cleared.", title="Log")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Could not clear log: {e}")


    def on_apply_settings(self):
        """Apply and save settings. Theme is applied here (not live)."""
        self.settings["default_format"] = self.settings_format_combo.get()
        self.settings["theme"] = self.settings_theme_combo.get()
        self.settings["default_download_path"] = self.default_download_path_entry.get() or str(DOWNLOADS_DIR)
        self.settings["cookies_path"] = self.settings_cookies_entry.get().strip()
        self.settings["use_smart_naming"] = bool(self.settings_smart_naming_switch.get())
        self.settings["show_toasts"] = bool(self.settings_toast_switch.get())
        self.settings["debug_mode"] = bool(self.settings_debug_switch.get())
        try:
            self.settings["max_concurrent_downloads"] = int(self.settings_max_dl_combo.get())
        except Exception:
            self.settings["max_concurrent_downloads"] = 1
        save_settings(self.settings)
        log_message(f"Settings applied: {self.settings}")
        self._apply_theme()  # theme applied only on save
        _toast(self, "Settings saved & applied.", title="Settings")


    def on_reset_defaults(self):
        """Reset settings to defaults."""
        if messagebox.askyesno(APP_NAME, "Reset all settings to default values?"):
            save_settings(DEFAULT_SETTINGS)
            self.settings = DEFAULT_SETTINGS.copy()
            self.settings_format_combo.set("mp4")
            self.settings_theme_combo.set("dark")
            self.default_download_path_entry.delete(0, "end")
            self.default_download_path_entry.insert(0, WINDOWS_DOWNLOADS_DIR)
            try:
                self.settings_cookies_entry.delete(0, "end")
            except Exception:
                pass
            try:
                self.settings_smart_naming_switch.select()
            except Exception:
                pass
            try:
                self.settings_toast_switch.select()
            except Exception:
                pass
            try:
                self.settings_debug_switch.deselect()
            except Exception:
                pass
            try:
                self.settings_max_dl_combo.set("1")
            except Exception:
                pass
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

    
    
    def on_fetch_playlist(self):
        """Fetch playlist items incrementally."""
        url = self.playlist_url_entry.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "Please enter a playlist URL.")
            return

        self.show_spinner("Fetching playlist items...")
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
                try:
                    meta = fetch_metadata_via_yt_dlp(url)
                except Exception:
                    meta = {}
                entry_hist = {
                    "title": Path(outp).stem if outp else entry.get("title",""),
                    "url": url,
                    "uploader": meta.get("uploader") if meta else "",
                    "duration": meta.get("duration_string") if meta else "",
                    "resolution": max_res,
                    "format": target_format,
                    "download_mode": "Playlist",
                    "download_path": outdir,
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

    

    def cancel_download(self):
        """Cancel current download."""
        self.current_task_cancelled = True
        self.download_proc.cancel()
        try:
            try: self.dl_download_btn.configure(state="normal")
            except Exception: pass
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

        if ev == "dl_item_progress":
            # In-place update — no rebuild, just touch the widgets
            queue_idx, pval, speed_text = item[1], item[2], item[3]
            try:
                with self._dl_queue_lock:
                    entry = self._dl_queue[queue_idx] if 0 <= queue_idx < len(self._dl_queue) else None
                if entry:
                    pbar = entry.get("_progress_bar")
                    if pbar:
                        try:
                            if pbar.winfo_exists():
                                pbar.set(pval)
                        except Exception:
                            pass
                    slbl = entry.get("_speed_lbl")
                    if slbl:
                        try:
                            if slbl.winfo_exists():
                                slbl.configure(text=speed_text)
                        except Exception:
                            pass
            except Exception:
                pass
            self._dl_update_summary()
            return

        if ev == "dl_overall_progress":
            # Legacy event — summary handles overall bar now; ignore
            return

        if ev == "dl_all_finished":
            completed, total = item[1], item[2]
            try:
                self.dl_download_btn.configure(state="normal")
            except Exception:
                pass
            self._dl_update_summary()
            _toast(self, f"Download finished: {completed}/{total}", title="Download")
            _outdir = self.settings.get("default_download_path", WINDOWS_DOWNLOADS_DIR)
            windows_notify(
                "Clipster",
                f"Download finished: {completed}/{total} completed.",
                open_path=_outdir
            )
            return

        if ev == "dl_item_status":
            idx, status, err = item[1], item[2], item[3]
            with self._dl_queue_lock:
                if 0 <= idx < len(self._dl_queue):
                    self._dl_queue[idx]["status"] = status
                    if status == "error":
                        self._dl_queue[idx]["error"] = err
            # Full rebuild needed: row layout changes (progress bar appears/disappears)
            self._dl_render_queue()
            self._dl_update_summary()
            return

        if ev == "dl_meta_ready":
            idx = item[1]
            with self._dl_queue_lock:
                if 0 <= idx < len(self._dl_queue):
                    self._dl_queue[idx]["status"] = "ready"
            self._dl_render_queue()
            self._dl_update_summary()
            return


        if ev == "meta_fetched":
            # Handled via dl_meta_ready in v1.3.0 queue system
            return

        if ev == "meta_error":
            # Handled via dl_meta_error in v1.3.0 queue system
            return

        if ev == "single_progress":
            # progress routed through dl_overall_progress in v1.3.0
            progress_value = item[1]
            try: self.dl_overall_progress.set(progress_value)
            except Exception: pass
            return

        if ev == "single_finished":
            # In v1.3.0 queue, dl_item_status "done" handles per-item completion
            return
        if ev == "single_error_restricted":
            err = item[1]
            messagebox.showerror(APP_NAME, "This video requires sign-in (age-restricted or members-only).\n\nTip: use yt-dlp with a cookies file.")
            try: self.dl_download_btn.configure(state="normal")
            except Exception: pass
            return

        if ev == "single_error":
            err = item[1]
            messagebox.showerror(APP_NAME, f"Download failed: {err}")
            try: self.dl_download_btn.configure(state="normal")
            except Exception: pass
            return
        if ev == "playlist_item_add":
            idx, entry = item[1], item[2]
            row = ctk.CTkFrame(self.playlist_scroll, height=80)
            row.grid_columnconfigure(1, weight=1)
            sel_var = ctk.BooleanVar(value=True)
            chk = ctk.CTkCheckBox(row, text="", variable=sel_var)
            chk.grid(row=0, column=0, padx=(8,6), pady=10)
            title_lbl = ctk.CTkLabel(row, text=f"{idx}. {entry.get('title','<No title>')}", anchor="w", font=ctk.CTkFont(size=12))
            title_lbl.grid(row=0, column=2, sticky="w", padx=(0, 8), pady=4)
            row.pack(fill="x", padx=6, pady=4)
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

        if ev == "pl_inline_items_ready":
            items = item[1]
            try:
                self._pl_render_items(items)
            except Exception as e:
                log_message(f"pl_inline_items_ready render error: {e}")
            return

        if ev == "pl_inline_error":
            err = item[1]
            try:
                self._pl_status_lbl.configure(text=f"❌ Error: {err}")
            except Exception:
                pass
            _toast(self, f"Playlist fetch failed: {err}", level="error")
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
            return


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
            _outdir = self.settings.get("default_download_path", WINDOWS_DOWNLOADS_DIR)
            windows_notify(
                "Clipster",
                f"Playlist finished: {completed}/{total} downloads complete.",
                open_path=_outdir
            )
            self.refresh_history()
            return

        if ev == "update_status":
            try:
                self.update_status_label.configure(text=item[1])
            except Exception:
                pass
            return

        if ev == "update_available":
            latest, data = item[1], item[2]
            self.latest_release_data = data
            try:
                self.update_status_label.configure(
                    text=f"🆕 New version available: {latest}\n(Current: {APP_VERSION})"
                )
            except Exception:
                pass
            return

        if ev == "update_install":
            new_exe_path = item[1]
            try: self.hide_spinner()
            except Exception: pass
            try:
                self.update_status_label.configure(text="✅ Download complete. Installing update...")
            except Exception:
                pass
            os.startfile(new_exe_path)
            self._close_window()
            return

if __name__ == "__main__":
    try:
        ensure_directories()    
        root = ctk.CTk()
        
        # Create and initialize the app directly (no splash screen)
        app = ClipsterApp(root)
        _app = app

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