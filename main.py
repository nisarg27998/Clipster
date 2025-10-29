"""
Clipster v1.2 - main.py
(Refined upgrade of v1.1)

Changes & Improvements:
  • Removed bottom status bar and cancel button.
  • Added themed, non-blocking toast notifications.
  • Replaced status updates with toast messages (e.g. “Fetching...”, “Download complete”).
  • Optimized UI responsiveness and reduced startup delay.
  • Minor bug fixes and smoother animations.
  • Codebase prepared for future playlist/history integration.

Dependencies:
  pip install customtkinter requests pillow

Place executables in /Assets/:
  - yt-dlp.exe
  - ffmpeg.exe
  - ffprobe.exe
  - ffplay.exe

Run on Windows with Python 3.13.
"""

import os
import sys
import re
import json
import time
import shutil
import queue
import threading
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
import customtkinter as ctk
from tkinter import filedialog, messagebox

from PIL import Image

# --------------------------------------------
# Branding / Config
# --------------------------------------------
APP_NAME = "Clipster"
APP_VERSION = "1.1"
ACCENT_COLOR = "#0078D7"
SECONDARY_COLOR = "#00B7C2"
SPLASH_TEXT = "Fetch. Download. Enjoy."

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "Assets"
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
YT_DLP_PROGRESS_RE = re.compile(r"\[download\]\s+([0-9]{1,3}\.[0-9])%")
YT_DLP_SPEED_RE = re.compile(r"at\s+([0-9\.]+\w+/s)")
YT_DLP_ETA_RE = re.compile(r"ETA\s+([0-9:]+)")

LOG_FILE = BASE_DIR / "clipster.log"

# --------------------------------------------
# Update check (GitHub latest release)
# --------------------------------------------
def check_latest_version():
    """Check GitHub for the latest release version."""
    try:
        import requests
        r = requests.get("https://api.github.com/repos/nisarg27998/Clipster/releases/latest", timeout=5)
        if r.status_code == 200:
            latest = r.json().get("tag_name", "")
            if latest and latest != f"v{APP_VERSION}":
                messagebox.showinfo(
                    "Update Available",
                    f"A newer version ({latest}) of {APP_NAME} is available on GitHub.\n\n"
                    "Visit the Releases page to download it."
                )
    except Exception as e:
        log_message(f"Update check failed: {e}")


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
    "default_format": "mp4",
    "theme": "dark",
    "embed_thumbnail": True,
    "default_download_path": str(DOWNLOADS_DIR),
    "cookies_path": ""
}

def load_settings():
    """Load settings from JSON file, falling back to defaults."""
    if not SETTINGS_FILE.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in DEFAULT_SETTINGS.items():
            if k not in data:
                data[k] = v
        return data
    except Exception:
        return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    """Save settings to JSON file."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        log_message(f"Failed to save settings: {e}")

def load_history():
    """Load download history from JSON file."""
    if not HISTORY_FILE.exists():
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def append_history(entry):
    """Append a new entry to the history JSON."""
    history = load_history()
    history.insert(0, entry)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

def delete_history_entry(index):
    """Delete a specific entry from history."""
    history = load_history()
    if 0 <= index < len(history):
        history.pop(index)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)

def clear_history():
    """Clear all history entries."""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

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

# --------------------------------------------
# Metadata via yt-dlp --dump-json (blocking small call)
# --------------------------------------------
def fetch_metadata_via_yt_dlp(url, timeout=30):
    """Fetch video metadata using yt-dlp."""
    if not YT_DLP_EXE.exists():
        raise FileNotFoundError("yt-dlp.exe not found in Assets/")
    cmd = [windows_quote(str(YT_DLP_EXE)), "--no-warnings", "--skip-download", "--dump-json", url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = proc.stdout.strip()
        if proc.returncode != 0:
            stderr = proc.stderr.strip() or proc.stdout.strip()
            if "Sign in to confirm your age" in stderr or "members-only" in stderr or "This video is only available for members" in stderr:
                raise RuntimeError("This video is age-restricted or members-only and requires sign-in. Clipster cannot download it.")
            raise RuntimeError(stderr or "yt-dlp failed to fetch metadata")
        if not out:
            raise RuntimeError("No metadata returned by yt-dlp")
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

# --------------------------------------------
# Download process wrapper (yt-dlp)
# --------------------------------------------
class DownloadProcess:
    """Manages a single yt-dlp download process."""
    def __init__(self):
        self.proc = None
        self._lock = threading.Lock()

    def start_download(self, url, outdir, filename_template, format_selector, cookies_path=None, progress_callback=None, finished_callback=None, error_callback=None):
        """Start a download thread."""
        thread = threading.Thread(target=self._run_download, args=(url, outdir, filename_template, format_selector, cookies_path, progress_callback, finished_callback, error_callback), daemon=True)
        thread.start()
        return thread

    def _run_download(self, url, outdir, filename_template, format_selector, cookies_path, progress_callback, finished_callback, error_callback):
        """Internal method to run yt-dlp subprocess."""
        if not YT_DLP_EXE.exists():
            if error_callback: error_callback("yt-dlp.exe not found in Assets/")
            return
        outtmpl = os.path.join(outdir, filename_template)
        cmd = [windows_quote(str(YT_DLP_EXE)), "--no-warnings", "--newline"]
        if cookies_path:
            cmd += ["--cookies", windows_quote(cookies_path)]
        cmd += ["-o", outtmpl, "-f", format_selector, url]

        try:
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True) as p:
                with self._lock:
                    self.proc = p
                output_path = None
                for raw_line in p.stdout:
                    line = raw_line.strip()
                    if "Sign in to confirm your age" in line or "This video is only available for members" in line or "This video is private" in line:
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
def download_thumbnail(url, target_path, timeout=20):
    """Download thumbnail from URL to local path."""
    try:
        r = requests.get(url, stream=True, timeout=timeout)
        r.raise_for_status()
        with open(target_path, "wb") as f:
            shutil.copyfileobj(r.raw, f)
        return True
    except Exception as e:
        log_message(f"download_thumbnail error: {e}")
        return False

def embed_thumbnail_with_ffmpeg(video_path, thumb_path):
    """Embed thumbnail into video using ffmpeg."""
    if not FFMPEG_EXE.exists():
        return False
    video_path = Path(video_path)
    thumb_path = Path(thumb_path)
    out_tmp = video_path.with_suffix(video_path.suffix + ".thumbtmp" + video_path.suffix)
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
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            if out_tmp.exists():
                out_tmp.unlink(missing_ok=True)
            log_message(f"FFmpeg embed failed: {proc.stderr}")
            return False
        backup = video_path.with_suffix(video_path.suffix + ".bak")
        try:
            video_path.replace(backup)
            out_tmp.replace(video_path)
            backup.unlink(missing_ok=True)
        except Exception:
            try:
                os.remove(str(video_path))
            except Exception:
                pass
            try:
                shutil.move(str(out_tmp), str(video_path))
            except Exception:
                return False
        return True
    except Exception as e:
        log_message(f"embed_thumbnail_with_ffmpeg exception: {e}")
        return False

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

class ClipsterApp:
    """Main application class for Clipster GUI."""
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} - {SPLASH_TEXT}")
        self.root.geometry("1000x700")
        self.root.minsize(900, 600)

        # Hide window initially to prevent flashing during setup
        self.root.withdraw()

        ensure_directories()
        missing = check_executables()
        if missing:
            messagebox.showwarning(APP_NAME, f"Missing executables in Assets/: {', '.join(missing)}")
            log_message(f"Missing executables: {missing}")

        self.settings = load_settings()
        self.history = load_history()

        ctk.set_appearance_mode(self.settings.get("theme", "dark"))

        self.download_proc = DownloadProcess()
        self.ui_queue = queue.Queue()
        self.current_task_cancelled = False

        # caches and mappings
        self._history_thumb_imgs = {}
        self._playlist_thumb_imgs = {}
        self._playlist_row_by_vid = {}
        self._playlist_row_order = []

        # drag ghost and state
        self._drag_source_row = None
        self._drag_ghost = None

        self._build_ui()
        self._enable_mica_effect()
        self.root.after(100, self._process_ui_queue)

        # Show window after setup to avoid flashing
        self.root.after(200, self._show_window_after_setup)

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
        png_path = BASE_DIR / "Assets" / "clipster.png"
        ico_path = BASE_DIR / "Assets" / "clipster.ico"

        try:
            if png_path.exists():
                img = Image.open(png_path).convert("RGBA")
                img.thumbnail((20, 20))
                icon_img = ctk.CTkImage(img, size=(20, 20))
            if ico_path.exists():
                self.root.iconbitmap(default=str(ico_path))
        except Exception:
            pass

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
        """Close the application."""
        self.root.destroy()

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
            img = Image.open(img_path).convert("RGBA")
            img.thumbnail(size)
            ctkimg = ctk.CTkImage(img, size=size)
            return ctkimg
        except Exception as e:
            log_message(f"_safe_create_ctkimage error for {img_path}: {e}")
            return None

    def _path_exists(self, p):
        """Check if path exists."""
        try:
            if not p:
                return False
            return Path(str(p)).exists()
        except Exception:
            return False

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
        """Apply theme to the application."""
        ctk.set_appearance_mode(self.settings.get("theme", "dark"))
        try:
            self.root.configure(fg_color=ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
        except Exception:
            pass
        self.refresh_history()
        self._update_titlebar_theme()
        self._enable_mica_effect()
        self.root.update_idletasks()

    def _on_theme_combo_changed(self, choice):
        """Called when the user picks a new theme from the combo box."""
        self.settings["theme"] = choice
        ctk.set_appearance_mode(choice)      # instant switch
        self._apply_theme()                  # update title-bar, Mica, etc.
        self.status_var.set(f"Theme changed to {choice}.")

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
                menu_win, text=val, fg_color="transparent", hover_color=hover_color, anchor="w",
                width=parent_widget.winfo_width() - 8, height=28,
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
                menu_win, text=label, fg_color="transparent", hover_color=hover_color, anchor="w",
                width=180, height=28, command=lambda c=callback, m=menu_win: (m.destroy(), c())
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
        """Build the main UI components."""
        try:
            self._create_titlebar()
        except Exception as e:
            log_message(f"_create_titlebar failed: {e}")

        #top_frame = ctk.CTkFrame(self.root, corner_radius=0)
        #top_frame.pack(fill="x", padx=12, pady=(12, 6))
        #title_lbl = ctk.CTkLabel(top_frame, text=APP_NAME, font=ctk.CTkFont(size=20, weight="bold"))
        #title_lbl.pack(side="left", padx=8)
        #splash_lbl = ctk.CTkLabel(top_frame, text=SPLASH_TEXT, font=ctk.CTkFont(size=12))
        #splash_lbl.pack(side="left", padx=12)

        self.tabs = ctk.CTkTabview(self.root, width=980, height=540)
        self.tabs.pack(padx=12, pady=6, fill="both", expand=True)
        self.tabs.add("Single Video")
        self.tabs.add("Batch Downloader")
        self.tabs.add("Playlist Downloader")
        self.tabs.add("History")
        self.tabs.add("Settings")

        self._build_single_tab(self.tabs.tab("Single Video"))
        self._build_batch_tab(self.tabs.tab("Batch Downloader"))
        self._build_playlist_tab(self.tabs.tab("Playlist Downloader"))
        self._build_history_tab(self.tabs.tab("History"))
        self._build_settings_tab(self.tabs.tab("Settings"))

        self.status_var = ctk.StringVar(value="Ready")
        status_bar = ctk.CTkFrame(self.root, height=40)
        status_bar.pack(fill="x", padx=12, pady=(6, 12))
        self.status_label = ctk.CTkLabel(status_bar, textvariable=self.status_var)
        self.status_label.pack(side="left", padx=8)
        self.cancel_btn = ctk.CTkButton(status_bar, text="Cancel Download", width=140, command=self.cancel_download, fg_color=ACCENT_COLOR)
        self.cancel_btn.pack(side="right", padx=8)
        self.cancel_btn.configure(state="disabled")

        self.spinner_overlay = None

    def _build_single_tab(self, parent):
        """Build UI for Single Video tab."""
        pad = 12
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="both", expand=True, padx=pad, pady=pad)
        left = ctk.CTkFrame(frame)
        left.pack(side="left", fill="y", padx=(0, 8), pady=4)

        ctk.CTkLabel(left, text="Video URL:", anchor="w").pack(padx=8, pady=(8, 0))
        self.single_url_entry = ctk.CTkEntry(left, width=520)
        self.single_url_entry.pack(padx=8, pady=(4, 8))

        self.fetch_meta_btn = ctk.CTkButton(left, text="Fetch Metadata", fg_color=ACCENT_COLOR, command=self.on_fetch_single_metadata)
        self.fetch_meta_btn.pack(padx=8, pady=6)

        ctk.CTkLabel(left, text="Resolution:", anchor="w").pack(padx=8, pady=(8, 0))
        self.single_resolution_combo = ctk.CTkComboBox(left, values=["Best Available"], width=200)
        self.single_resolution_combo.set("Best Available")
        self.single_resolution_combo.pack(padx=8, pady=6)

        ctk.CTkLabel(left, text="Format:", anchor="w").pack(padx=8, pady=(8, 0))
        self.single_format_combo = ctk.CTkComboBox(left, values=ALLOWED_FORMATS, width=200)
        self.single_format_combo.set(self.settings.get("default_format", "mp4"))
        self.single_format_combo.pack(padx=8, pady=6)

        self.single_embed_var = ctk.BooleanVar(value=self.settings.get("embed_thumbnail", True))
        ctk.CTkCheckBox(left, text="Embed thumbnail", variable=self.single_embed_var).pack(anchor="w", padx=8, pady=4)

        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.pack(padx=8, pady=(4, 12))
        self.single_download_btn = ctk.CTkButton(btn_frame, text="Download", fg_color=ACCENT_COLOR, command=self.on_single_download)
        self.single_download_btn.pack(side="left", padx=6)
        self.single_cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", command=self.cancel_download)
        self.single_cancel_btn.pack(side="left", padx=6)

        ctk.CTkLabel(left, text="Progress:", anchor="w").pack(padx=8, pady=(6, 0))
        self.single_progress = ctk.CTkProgressBar(left, width=320)
        self.single_progress.set(0)
        self.single_progress.pack(padx=8, pady=(4, 8))
        self.single_progress_label = ctk.CTkLabel(left, text="")
        self.single_progress_label.pack(padx=8, pady=(2, 8))

        right = ctk.CTkFrame(frame)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=4)

        self.meta_title_var = ctk.StringVar(value="")
        ctk.CTkLabel(right, textvariable=self.meta_title_var, font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="nw", padx=8, pady=(8, 0))
        self.meta_uploader_var = ctk.StringVar(value="")
        ctk.CTkLabel(right, textvariable=self.meta_uploader_var, font=ctk.CTkFont(size=12)).pack(anchor="nw", padx=8, pady=2)
        self.meta_duration_var = ctk.StringVar(value="")
        ctk.CTkLabel(right, textvariable=self.meta_duration_var, font=ctk.CTkFont(size=12)).pack(anchor="nw", padx=8, pady=2)

        self.thumbnail_label = ctk.CTkLabel(right, text="Thumbnail preview", width=320, height=180, anchor="center")
        self.thumbnail_label.pack(anchor="nw", padx=8, pady=12)

    def _build_batch_tab(self, parent):
        """Build UI for Batch Downloader tab."""
        pad = 12
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="both", expand=True, padx=pad, pady=pad)
        top = ctk.CTkFrame(frame)
        top.pack(fill="x", pady=6)
        ctk.CTkLabel(top, text="Paste multiple video URLs (one per line):").pack(side="left", padx=6)
        self.batch_maxres_combo = ctk.CTkComboBox(top, values=["Best Available", "720p", "1080p", "1440p", "2160p"], width=180)
        self.batch_maxres_combo.set("Best Available")
        self.batch_maxres_combo.pack(side="right", padx=6)

        self.batch_text = ctk.CTkTextbox(frame, width=800, height=260)
        self.batch_text.pack(padx=6, pady=6, fill="both", expand=True)

        bottom = ctk.CTkFrame(frame)
        bottom.pack(fill="x", pady=6)
        ctk.CTkLabel(bottom, text="Format:").pack(side="left", padx=6)
        self.batch_format_combo = ctk.CTkComboBox(bottom, values=ALLOWED_FORMATS)
        self.batch_format_combo.set(self.settings.get("default_format", "mp4"))
        self.batch_format_combo.pack(side="left", padx=6)
        ctk.CTkButton(bottom, text="Download Batch", fg_color=ACCENT_COLOR, command=self.on_batch_download).pack(side="right", padx=6)

        ctk.CTkLabel(frame, text="Overall Progress:").pack(anchor="w", padx=6, pady=(8, 0))
        self.batch_overall_progress = ctk.CTkProgressBar(frame)
        self.batch_overall_progress.set(0)
        self.batch_overall_progress.pack(fill="x", padx=6, pady=(2, 6))

    def _build_playlist_tab(self, parent):
        """Build UI for Playlist Downloader tab."""
        pad = 12
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="both", expand=True, padx=pad, pady=pad)

        ctk.CTkLabel(frame, text="Playlist URL:").pack(anchor="nw", padx=6, pady=(6, 0))
        self.playlist_url_entry = ctk.CTkEntry(frame, width=720)
        self.playlist_url_entry.pack(padx=6, pady=(4, 8))
        fetch_btn = ctk.CTkButton(frame, text="Fetch Playlist Items", fg_color=ACCENT_COLOR, command=self.on_fetch_playlist)
        fetch_btn.pack(padx=6, pady=(4, 8))

        self.playlist_progress_label = ctk.CTkLabel(frame, text="", anchor="w")
        self.playlist_progress_label.pack(anchor="nw", padx=6, pady=(4, 0))

        ctk.CTkLabel(frame, text="Playlist Items:").pack(anchor="nw", padx=6, pady=(6, 0))
        self.playlist_scroll = ctk.CTkScrollableFrame(frame, height=280)
        self.playlist_scroll.pack(fill="both", expand=True, padx=6, pady=(4, 12))

        bottom = ctk.CTkFrame(frame)
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

        ctk.CTkButton(bottom, text="Download Playlist (selected order)", fg_color=ACCENT_COLOR, command=self.on_download_playlist).pack(side="right", padx=6)

        ctk.CTkLabel(frame, text="Overall Progress:").pack(anchor="w", padx=6, pady=(8, 0))
        self.playlist_overall_progress = ctk.CTkProgressBar(frame)
        self.playlist_overall_progress.set(0)
        self.playlist_overall_progress.pack(fill="x", padx=6, pady=(2, 6))

    def _build_history_tab(self, parent):
        """Build UI for History tab."""
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        top = ctk.CTkFrame(frame)
        top.pack(fill="x", pady=(0, 8))
        ctk.CTkButton(top, text="Clear History", command=self.clear_history_prompt, fg_color="tomato").pack(side="left", padx=6)

        self.history_scroll = ctk.CTkScrollableFrame(frame, height=480)
        self.history_scroll.pack(fill="both", expand=True, padx=6, pady=6)

        self.refresh_history()

    def refresh_history(self):
        """Refresh history list UI."""
        for widget in self.history_scroll.winfo_children():
            widget.destroy()
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

            threading.Thread(target=thumb_task, args=(idx, entry), daemon=True).start()

    def _create_history_row(self, idx, entry):
        """Create a row for history item."""
        row_frame = ctk.CTkFrame(self.history_scroll, height=100)
        row_frame.grid_columnconfigure(1, weight=1)

        thumb_label = ctk.CTkLabel(row_frame, text="No\nthumbnail", width=140, height=80, anchor="center")
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
        redl_btn = ctk.CTkButton(btn_frame, text="Re-Download", fg_color=ACCENT_COLOR, width=110,
                                 command=lambda e=entry, i=idx: self.re_download(e, i))
        redl_btn.pack(pady=(6,4))
        del_btn = ctk.CTkButton(btn_frame, text="Delete", fg_color="tomato", width=110,
                                command=lambda i=idx: (delete_history_entry(i), self.refresh_history()))
        del_btn.pack(pady=(4,6))

        row_frame._thumb_label = thumb_label
        row_frame._entry = entry
        row_frame._index = idx

        return row_frame

    def _extract_video_id(self, url):
        """Extract video ID from YouTube URL."""
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

    # ──────────────────────────────────────────────────────────────
    #  SETTINGS TAB – replace the whole block that creates the format entry
    # ──────────────────────────────────────────────────────────────
    def _build_settings_tab(self, parent):
        """Build UI for Settings tab."""
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        # ---------- Default format ----------
        ctk.CTkLabel(frame, text="Default format:").pack(anchor="nw", padx=8, pady=(8, 0))
        self.settings_format_combo = ctk.CTkComboBox(
            frame, values=ALLOWED_FORMATS, width=180
        )
        self.settings_format_combo.set(self.settings.get("default_format", "mp4"))
        self.settings_format_combo.pack(anchor="nw", padx=8, pady=6)

        # ---------- Theme (real ComboBox) ----------
        ctk.CTkLabel(frame, text="Theme:").pack(anchor="nw", padx=8, pady=(8, 0))
        self.settings_theme_combo = ctk.CTkComboBox(
            frame,
            values=["dark", "light"],
            width=120,
            command=self._on_theme_combo_changed   # <-- NEW
        )
        self.settings_theme_combo.set(self.settings.get("theme", "dark"))
        self.settings_theme_combo.pack(anchor="nw", padx=8, pady=6)

        # ---------- Embed thumbnail default ----------
        self.settings_embed_var = ctk.BooleanVar(value=self.settings.get("embed_thumbnail", True))
        ctk.CTkCheckBox(frame, text="Embed thumbnails by default", variable=self.settings_embed_var).pack(anchor="nw", padx=8, pady=6)
        
        # ---------- Default download folder ----------
        ctk.CTkLabel(frame, text="Default download folder:").pack(anchor="nw", padx=8, pady=(8, 0))
        self.default_download_path_entry = ctk.CTkEntry(frame, width=420)
        self.default_download_path_entry.insert(0, self.settings.get("default_download_path", str(DOWNLOADS_DIR)))
        self.default_download_path_entry.pack(anchor="nw", padx=8, pady=6)
        ctk.CTkButton(frame, text="Choose Folder...", command=self.on_choose_download_folder).pack(anchor="nw", padx=8, pady=6)

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(anchor="nw", padx=8, pady=(16, 6))

        ctk.CTkButton(btn_frame, text="Apply Settings", fg_color=ACCENT_COLOR, command=self.on_apply_settings).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_frame, text="Reset to Defaults", fg_color="gray", command=self.on_reset_defaults).pack(side="left", padx=4)
        ctk.CTkButton(btn_frame, text="Open Log File", fg_color=SECONDARY_COLOR, command=open_log_file).pack(side="left", padx=8)

    def on_apply_settings(self):
        """Apply and save settings."""
        self.settings["default_format"] = self.settings_format_combo.get()
        self.settings["theme"] = self.settings_theme_combo.get()
        self.settings["embed_thumbnail"] = self.settings_embed_var.get()
        self.settings["default_download_path"] = self.default_download_path_entry.get() or str(DOWNLOADS_DIR)
        save_settings(self.settings)
        log_message(f"Settings applied: {self.settings}")
        self._apply_theme()
        self.status_var.set("Settings applied.")

    def on_reset_defaults(self):
        """Reset settings to defaults."""
        if messagebox.askyesno(APP_NAME, "Reset all settings to default values?"):
            save_settings(DEFAULT_SETTINGS)
            self.settings = DEFAULT_SETTINGS.copy()
            self.settings_format_combo.delete(0, "end")
            self.settings_format_combo.insert(0, "mp4")
            self.settings_theme_combo.delete(0, "end")
            self.settings_theme_combo.insert(0, "dark")
            self.settings_embed_var.set(True)
            self.default_download_path_entry.delete(0, "end")
            self.default_download_path_entry.insert(0, str(DOWNLOADS_DIR))
            log_message("Settings reset to defaults")
            self._apply_theme()
            self.status_var.set("Settings reset to defaults.")

    def on_choose_download_folder(self):
        """Choose default download folder."""
        path = filedialog.askdirectory(initialdir=self.settings.get("default_download_path", str(DOWNLOADS_DIR)))
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
        """Show spinner overlay."""
        if self.spinner_overlay:
            return
        overlay = ctk.CTkToplevel(self.root)
        overlay.geometry("320x120")
        overlay.transient(self.root)
        overlay.grab_set()
        overlay.title("")
        overlay.attributes("-topmost", True)
        overlay.resizable(False, False)
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 160
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 60
        overlay.geometry(f"+{x}+{y}")
        lbl = ctk.CTkLabel(overlay, text=text, font=ctk.CTkFont(size=14))
        lbl.pack(pady=(20, 8))
        pb = ctk.CTkProgressBar(overlay, mode="indeterminate")
        pb.pack(fill="x", padx=24, pady=(4, 20))
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
        threading.Thread(target=task, daemon=True).start()

    def on_single_download(self):
        """Start download for single video."""
        url = self.single_url_entry.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "Please enter a video URL.")
            return
        fmt = self.single_format_combo.get()
        embed_thumb = self.single_embed_var.get()
        res_label = self.single_resolution_combo.get()
        outdir = self.settings.get("default_download_path", str(DOWNLOADS_DIR))
        fmt_selector = build_format_selector_for_format_and_res(fmt, res_label)
        filename_template = "%(title)s.%(ext)s"
        self.single_download_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.status_var.set("Downloading...")
        self.single_progress.set(0)
        self.single_progress_label.configure(text="Starting...")
        self.current_task_cancelled = False

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
        """Start batch download."""
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
        embed_thumb = self.batch_embed_var.get()
        outdir = self.settings.get("default_download_path", str(DOWNLOADS_DIR))
        fmt_selector = build_batch_format_selector(target_format, max_res)
        self.cancel_btn.configure(state="normal")
        self.status_var.set(f"Downloading batch ({len(urls)} items)...")
        self.batch_overall_progress.set(0)
        total = len(urls)
        completed = 0

        cookies_path = self.settings.get("cookies_path", "") or None

        def batch_task():
            nonlocal completed
            for idx, url in enumerate(urls):
                if self.current_task_cancelled:
                    break
                self.ui_queue.put(("batch_item_start", idx+1, url))
                finished_event = threading.Event()
                last_output_path = {"path": None}
                def progress_callback(percent, speed, eta, raw_line):
                    self.ui_queue.put(("batch_item_progress", idx+1, percent or 0.0, speed, eta))
                def finished_callback(output_path):
                    last_output_path["path"] = output_path
                    finished_event.set()
                def error_callback(err):
                    self.ui_queue.put(("batch_item_error", idx+1, str(err)))
                    finished_event.set()
                self.download_proc.start_download(url, outdir, "%(title)s.%(ext)s", fmt_selector, cookies_path, progress_callback, finished_callback, error_callback)
                while not finished_event.is_set():
                    if self.current_task_cancelled:
                        self.download_proc.cancel()
                        break
                    time.sleep(0.2)
                outp = last_output_path.get("path") if last_output_path.get("path") else None
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
                if outp and embed_thumb:
                    try:
                        meta = fetch_metadata_via_yt_dlp(url)
                        thumb_url = meta.get("thumbnail")
                        if thumb_url:
                            thumbfile = TEMP_DIR / f"thumb_{int(time.time())}.jpg"
                            ok = download_thumbnail(thumb_url, str(thumbfile))
                            if ok:
                                embedded_flag = embed_thumbnail_with_ffmpeg(outp, thumbfile)
                    except Exception:
                        embedded_flag = False
                try:
                    duration = meta.get("duration_string") if meta else ""
                except:
                    duration = ""
                entry = {
                    "title": Path(outp).stem if outp else "",
                    "url": url,
                    "uploader": meta.get("uploader") if meta else "",
                    "duration": duration,
                    "resolution": max_res,
                    "format": target_format,
                    "download_mode": "Batch",
                    "download_path": outdir,
                    "thumbnail_embedded": bool(embedded_flag),
                    "redownloaded": False,
                    "date": now_str()
                }
                append_history(entry)
                completed += 1
                self.ui_queue.put(("batch_item_done", completed, total))
            self.ui_queue.put(("batch_finished", completed, total))

        self.current_task_cancelled = False
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
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, universal_newlines=True)
                index = 0
                for line in iter(proc.stdout.readline, ''):
                    if line is None:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        title = data.get("title") or "<No title>"
                        vid_id = data.get("id")
                        if not vid_id:
                            vid_id = data.get("url") or None
                        if not vid_id:
                            continue
                        full_url = f"https://youtube.com/watch?v={vid_id}"
                        entry = {"title": title, "url": full_url, "id": vid_id}
                        index += 1
                        self.ui_queue.put(("playlist_item_add", index, entry))
                    except Exception:
                        continue

                try:
                    proc.stdout.close()
                except Exception:
                    pass
                proc.wait(timeout=10)
                self.ui_queue.put(("playlist_fetch_done", index))
            except Exception as e:
                log_message(f"Playlist fetch error: {e}")
                self.ui_queue.put(("playlist_error", str(e)))

        threading.Thread(target=task, daemon=True).start()

    def on_download_playlist(self):
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
        embed_thumb = self.playlist_embed_var.get()
        outdir = self.settings.get("default_download_path", str(DOWNLOADS_DIR))
        fmt_selector = build_batch_format_selector(target_format, max_res)

        self.cancel_btn.configure(state="normal")
        self.status_var.set(f"Downloading {len(selected_entries)} selected items...")
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

                self.download_proc.start_download(url, outdir, "%(title)s.%(ext)s", fmt_selector, cookies_path, progress_callback, finished_callback, error_callback)

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
            self.status_var.set("URL copied to clipboard.")
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
            self.status_var.set("Removed item from playlist view.")

    def _on_row_button_press(self, event, row):
        """Start drag operation."""
        self._drag_source_row = row
        row.lift()
        if not self._drag_ghost:
            self._drag_ghost = ctk.CTkFrame(self.playlist_scroll, height=6, fg_color=ACCENT_COLOR)
        row._drag_start_y = event.y_root

    def _on_row_motion(self, event, row):
        """Handle drag motion with ghost indicator."""
        if not self._drag_source_row:
            return
        pointer_y = event.y_root - self.playlist_scroll.winfo_rooty()
        children = self.playlist_scroll.winfo_children()
        target_index = None
        for idx, child in enumerate(children):
            cy = child.winfo_y() + child.winfo_height() // 2
            if pointer_y < cy:
                target_index = idx
                break
        if target_index is None:
            target_index = len(children)
        try:
            if self._drag_ghost.winfo_ismapped():
                self._drag_ghost.pack_forget()
        except Exception:
            pass
        visual_children = [c for c in children if c is not self._drag_source_row and c is not self._drag_ghost]
        try:
            for c in visual_children:
                c.pack_forget()
            inserted = False
            for i, c in enumerate(visual_children):
                if i == target_index and not inserted:
                    self._drag_ghost.pack(fill="x", padx=6, pady=2)
                    inserted = True
                c.pack(fill="x", padx=6, pady=4)
            if not inserted:
                self._drag_ghost.pack(fill="x", padx=6, pady=2)
        except Exception:
            pass

    def _on_row_release(self, event, row):
        """Finish drag and reorder rows."""
        if not self._drag_source_row:
            return
        try:
            if self._drag_ghost and self._drag_ghost.winfo_ismapped():
                children = [c for c in self.playlist_scroll.winfo_children() if c is not self._drag_ghost]
                for c in children:
                    c.pack_forget()
                inserted = False
                for c in children:
                    if not inserted:
                        if c.winfo_y() > self._drag_source_row.winfo_y():
                            self._drag_source_row.pack_forget()
                            self._drag_source_row.pack(fill="x", padx=6, pady=4)
                            inserted = True
                    c.pack(fill="x", padx=6, pady=4)
                if not inserted:
                    self._drag_source_row.pack_forget()
                    self._drag_source_row.pack(fill="x", padx=6, pady=4)
            if self._drag_ghost:
                try:
                    self._drag_ghost.pack_forget()
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            self._drag_source_row = None
            self._rebuild_playlist_order()

    def _rebuild_playlist_order(self):
        """Rebuild playlist row order based on current UI."""
        order = []
        for child in self.playlist_scroll.winfo_children():
            if getattr(child, "_video_id", None):
                order.append(child._video_id)
        self._playlist_row_order = order

    def re_download(self, entry, index_in_history=None):
        """Re-download a history entry."""
        url = entry.get("url")
        fmt = entry.get("format", self.settings.get("default_format", "mp4"))
        res = entry.get("resolution", "Best Available")
        outdir = entry.get("download_path", self.settings.get("default_download_path", str(DOWNLOADS_DIR)))
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
        self.download_proc.start_download(url, outdir, "%(title)s.%(ext)s", fmt_selector, cookies_path, progress_callback, finished_callback, error_callback)

    def cancel_download(self):
        """Cancel current download."""
        self.current_task_cancelled = True
        self.download_proc.cancel()
        self.cancel_btn.configure(state="disabled")
        try:
            self.single_download_btn.configure(state="normal")
        except Exception:
            pass
        self.status_var.set("Download cancelled.")

    def _process_ui_queue(self):
        """Process UI update queue."""
        try:
            while True:
                item = self.ui_queue.get_nowait()
                self._handle_ui_event(item)
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
            if thumb_local and os.path.exists(str(thumb_local)):
                try:
                    ctkimg = self._safe_create_ctkimage(str(thumb_local), (320, 180))
                    if ctkimg:
                        self.thumbnail_label.configure(image=ctkimg, text="")
                        self.thumbnail_label.image = ctkimg
                    else:
                        self.thumbnail_label.configure(text="Thumbnail saved")
                except Exception:
                    self.thumbnail_label.configure(text="Thumbnail saved")
            else:
                self.thumbnail_label.configure(text="No thumbnail available")
            self.status_var.set("Metadata fetched.")
            return

        if ev == "meta_error":
            err = item[1]
            self.fetch_meta_btn.configure(state="normal")
            self.hide_spinner()
            if "age-restricted" in err.lower() or "sign in to confirm your age" in err.lower() or "members-only" in err.lower():
                messagebox.showerror(APP_NAME, "This video is age-restricted or members-only and requires sign-in. Clipster cannot download it.\n\nTip: use yt-dlp with a cookies file (manual).")
            else:
                messagebox.showerror(APP_NAME, f"Failed to fetch metadata: {err}")
            self.status_var.set("Ready")
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
            output_path, fmt, embed_thumb, url = item[1], item[2], item[3], item[4]
            if not output_path:
                outdir = self.settings.get("default_download_path", str(DOWNLOADS_DIR))
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
                "download_path": str(Path(output_path).parent) if output_path else self.settings.get("default_download_path", str(DOWNLOADS_DIR)),
                "thumbnail_embedded": bool(embedded_flag),
                "redownloaded": False,
                "date": now_str()
            }
            append_history(entry)
            self.single_download_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            self.single_progress.set(0)
            self.single_progress_label.configure(text="")
            self.status_var.set("Download finished.")
            messagebox.showinfo(APP_NAME, f"Download finished: {output_path}")
            self.refresh_history()
            return

        if ev == "single_error_restricted":
            err = item[1]
            self.single_download_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            self.hide_spinner()
            messagebox.showerror(APP_NAME, "This video requires you to be signed in (age-restricted or members-only). Clipster cannot download it without authentication.\n\nTip: use yt-dlp with a cookies file.")
            self.status_var.set("Ready")
            return

        if ev == "single_error":
            err = item[1]
            self.single_download_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
            self.hide_spinner()
            self.single_progress.set(0)
            self.single_progress_label.configure(text="")
            messagebox.showerror(APP_NAME, f"Download failed: {err}")
            self.status_var.set("Ready")
            return

        if ev == "batch_item_start":
            idx, url = item[1], item[2]
            self.status_var.set(f"Downloading item {idx}...")
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
            self.status_var.set(f"Batch progress: {completed}/{total}")
            self.refresh_history()
            return

        if ev == "batch_finished":
            completed, total = item[1], item[2]
            self.cancel_btn.configure(state="disabled")
            self.batch_overall_progress.set(1.0)
            self.status_var.set(f"Batch finished: {completed}/{total}")
            messagebox.showinfo(APP_NAME, f"Batch finished: {completed}/{total}")
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

            row.bind("<Button-1>", lambda ev, r=row: self._on_row_button_press(ev, r))
            row.bind("<B1-Motion>", lambda ev, r=row: self._on_row_motion(ev, r))
            row.bind("<ButtonRelease-1>", lambda ev, r=row: self._on_row_release(ev, r))
            for child in row.winfo_children():
                child.bind("<Button-1>", lambda ev, r=row: self._on_row_button_press(ev, r))
                child.bind("<B1-Motion>", lambda ev, r=row: self._on_row_motion(ev, r))
                child.bind("<ButtonRelease-1>", lambda ev, r=row: self._on_row_release(ev, r))

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
            threading.Thread(target=thumb_task, args=(entry,), daemon=True).start()
            return

        if ev == "playlist_fetch_done":
            total = item[1]
            self.hide_spinner()
            self.status_var.set(f"Fetched {total} playlist items.")
            try:
                self.playlist_progress_label.configure(text=f"Fetched {total} items.")
            except Exception:
                pass
            return

        if ev == "playlist_error":
            err = item[1]
            self.hide_spinner()
            messagebox.showerror(APP_NAME, f"Playlist error: {err}")
            self.status_var.set("Ready")
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
            self.status_var.set("Re-download finished.")
            messagebox.showinfo(APP_NAME, f"Re-download finished: {output_path}")
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
                        row._progress.destroy()
                except Exception:
                    pass
            messagebox.showerror(APP_NAME, f"Playlist item error: {err}")
            return

        if ev == "playlist_seq_item_done":
            completed, total, vid = item[1], item[2], item[3]
            overall = completed / total if total else 0.0
            self.playlist_overall_progress.set(overall)
            self.status_var.set(f"Playlist progress: {completed}/{total}")
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
            self.cancel_btn.configure(state="disabled")
            self.playlist_overall_progress.set(1.0)
            self.status_var.set(f"Playlist finished: {completed}/{total}")
            messagebox.showinfo(APP_NAME, f"Playlist finished: {completed}/{total}")
            self.refresh_history()
            return

if __name__ == "__main__":
    try:
        ensure_directories()
        root = ctk.CTk()
        app = ClipsterApp(root)

        # Check for updates shortly after launch
        root.after(2000, check_latest_version)

        root.protocol("WM_DELETE_WINDOW", root.destroy)
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