# 🧾 Changelog

All notable changes to **Clipster** will be documented in this file.

---

## 📦 v1.2.2 — *Stable & Thread-Safe Core* (November 2025)

### 🧠 Under-the-Hood Improvements
- 🔒 **Thread-safe JSON handling** — Settings and History now use atomic file writes and file locks to prevent corruption.
- 🧵 **Bounded threading** — All background work now runs through a **ThreadPoolExecutor**, eliminating unbounded thread creation.
- 🚦 **UI-safe threading model** — Every background task now communicates with the main thread via a **UI queue**, ensuring zero `tkinter` thread violations.
- 🧩 **Graceful shutdown** — Cancels active downloads, safely shuts down worker threads, and cleans temporary files before exit.
- ⚙️ **Robust subprocess handling** — All `yt-dlp` and `FFmpeg` calls now run with strict error checking, timeouts, and safe stderr capture.
- 🪶 **Improved stability under heavy load** — No more random UI freezes or orphaned threads when fetching large playlists.

### ✨ Enhancements
- 🪄 Unified **thumbnail downloads** under the thread pool for consistent performance.
- 🧾 Added `"debug_mode"` in settings for detailed logging (optional toggle in future versions).
- 💬 `safe_ui_call()` and `log_debug()` utilities for cleaner internal logic.
- 🎨 Minor UI polish — smoother shutdown transitions and safer toast handling.

### 🐞 Bug Fixes
- 🧯 Fixed rare race condition when saving history after multiple downloads.
- 🧹 Prevented “zombie” threads if multiple metadata fetches are triggered quickly.
- 📁 Ensured temporary thumbnail files are cleaned up after embedding.
- ✅ Fixed potential UI crashes during rapid theme switching or shutdown.

---

## 📦 v1.2.1 — *Faster, Smarter, Cleaner* (October 2025)

### ✨ New Features
- 🖼️ Added **thumbnail extraction** option after metadata fetch
- 🪄 Introduced **non-blocking toast notifications** for smoother UX

### ⚙️ Improvements
- ⚡ **Faster startup** and UI responsiveness
- 🚫 **Hidden yt-dlp and FFmpeg windows** during operations
- 💾 Default save path now points to the user’s **Windows “Downloads”** folder
- 🎞️ Improved **thumbnail fetching reliability** (multiple fallbacks)
- 🧱 Optimized **FFmpeg integration** with safe temp file handling
- 🎨 Auto-refresh **drag ghost** on theme change to fix desyncs

### 🐞 Bug Fixes
- 🔢 Fixed **playlist overcount issue**
- 🧹 Removed **bottom status bar** and cancel button
- 🎨 Fixed **theme switching** drag ghost desync
- ✅ Improved **metadata parsing** and error handling

---

## 📦 v1.2.0 — *Stability Update* (September 2025)

### Highlights
- 🎞️ Added **per-row progress indicators** for playlists
- 📂 Introduced **“Save selection as .txt”** feature
- 🧩 Added **context menu options** (Play, Copy URL, Remove)
- 🪄 Added **animated drag ghost** for playlist reordering
- 💾 Persistent **Settings** and **History** system
- ⚙️ General UI and performance refinements

---

## 📦 v1.1.0 — *Initial Public Release* (August 2025)

- 🚀 Initial release of **Clipster**
- 🧱 Core downloader with **yt-dlp** + **FFmpeg**
- 🎨 Custom **Mica-themed** Windows 11 interface
- 🎞️ Single and Playlist download support
- 📸 Automatic **thumbnail embedding**
- 🌙 Dark / Light theme support

---

> “Fetch. Download. Enjoy.” — **Clipster**
