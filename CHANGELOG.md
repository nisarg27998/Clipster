# 🧾 Changelog

All notable changes to **Clipster** are documented here.

---

# Changelog

## [1.2.8] - 2026-02-17

### 🚀 Major Improvements

- 🔔 **Windows Native Notifications**
  - Replaced in-app completion toasts with real Windows 11 notifications.
  - Click notification to open downloaded file.
  - Cleaner, OS-integrated experience.

- ⏸️ **Pause / Resume Support (Single Downloads)**
  - Added pause & resume functionality for active downloads.
  - Proper state reset on cancel.
  - Stable process termination handling.

- 🗂️ **Smart Download Folder Naming**
  - Consistent filename templates across:
    - Single downloads
    - Batch downloads
    - Playlist downloads
    - Re-downloads
  - Safer filename sanitization.

### 🛠 Stability & Architecture

- Hardened UI thread safety using guarded `winfo_exists()` checks.
- Improved atomic JSON history writes.
- Improved subprocess handling & Windows console suppression.
- Improved shutdown logic for executor & background workers.

### 🎨 UI & UX

- Better progress synchronization in batch & playlist modes.
- Cleaner toast logic with thread-safe wrapper.
- Improved history thumbnail handling.
- Minor UI polish & consistency fixes.

---

## [1.2.7] - 2026-02-10
### Added
- **Splash Screen:** Added a modern splash screen on startup to mask the GUI initialization delay (`SplashScreen` class).
- **Clear History:** Added functionality to clear the entire download history.
- **Fade-out Animation:** Implemented smooth fade-out transitions for the splash screen.

### Changed
- **Startup Logic:** Refactored `main` execution to support the splash screen lifecycle before loading the main `ClipsterApp`.
- Updated version constants to 1.2.7.

---\

## [1.2.6] - 2026-02-02
### Added
- Implementation of global locks for thread-safe history read/write operations to prevent data corruption.
- Added graceful cleanup logic for temporary files and memory during application shutdown.

### Fixed
- **Core:** Updated `yt-dlp` to the latest version to resolve download throttling and extraction errors.
- **Stability:** Fixed `AttributeError` related to history loading state.
- **Process Management:** Refactored `DownloadProcess` to properly handle task cancellation and eliminate "zombie" background processes.

### Changed
- Improved history rendering logic with better state management.

---

## 📦 v1.2.4 — *Polish & Precision Update* (November 2025)

### ⚡ Performance & Stability
- 🚀 **Further Optimized Startup:** reduced GUI initialization delay by refining thread scheduling.
- 🧩 **Executor Lifecycle Fix:** executor shutdown logic corrected to ensure graceful termination.
- 🧠 **Lazy Imports Finalized:** all non-critical imports now dynamically loaded at runtime.
- 🧾 **Safer Metadata Fetching:** improved handling of malformed or restricted YouTube links.
- 🧹 **Removed Legacy Code:** deleted unused functions and placeholder methods for cleaner architecture.

### 🎨 UI & UX Enhancements
- 🌈 **Refined Dropdown Menus:** smoother fade-in and rounded-corner styling.
- 🪄 **Improved Toast Animations:** consistent transparency across light/dark themes.
- 🌙 **Instant Theme Sync:** titlebar and Mica refresh immediately after theme change.
- 🖼️ **Thumbnail Save Behavior:** now checks cache before re-downloading.

### 🐞 Fixes
- ✅ Fixed potential missed executor shutdown in `graceful_shutdown`.
- ✅ Fixed rare UI race condition during history rendering.
- ✅ Fixed `DownloadProcess.shutdown()` placeholder warning.
- ✅ Removed unused `check_latest_version()` function.