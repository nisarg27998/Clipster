# 🧾 Changelog

All notable changes to **Clipster** are documented here.

---

## [1.3.3] - 2026-04-25

### 🚀 Improvements

- **Native Notifications**: Replaced custom UI toasts with native Windows 11 system notifications (`win11toast`) for tray updates.
- **High-DPI Awareness**: App now explicitly sets Per-Monitor DPI Awareness before UI creation to prevent blurry text/rendering on modern high-resolution displays.
- **Single Instance Lock**: Added a Windows Mutex check to prevent multiple instances of the app from running. Launching the app again now brings the already-running instance to the foreground.
- **Standardized App Data**: Moved all app data (folders like `Assets`, `temp`, `downloads`, and files like `settings.json`, `history.json`) out of the executable folder and into `%LOCALAPPDATA%\Clipster` to keep the user's directories clean and prevent permission errors.
- **Close Behavior**: Modified the title bar's "X" close button to fully exit the application safely rather than minimizing it to the system tray.

### 🐞 Fixes

- **Python Syntax Fix**: Fixed a `SyntaxError` (`name 'YT_DLP_EXE' is used prior to global declaration`) in the auto-update background task.
- **PyInstaller Resource Resolution**: Added `_bootstrap_assets()` to seamlessly copy bundled tools to persistent storage on the first run of a `--onefile` build, preventing "file not found" errors and allowing in-place executable updates.

---

## [1.3.2] - 2026-03-09

### 🚀 Improvements

- Improved download queue performance
- Optimized per-item progress updates (reduced UI redraw)
- Improved metadata fetching logic
- Improved playlist sequential metadata fetch pipeline

### 🧠 Stability

- Better thread safety in download queue updates
- Improved cancellation handling
- Reduced UI race conditions during progress updates
- Minor performance optimizations across UI rendering

### 🎨 UI

- Minor visual refinements in queue rows
- Improved status badge animations

---

## [1.3.1] - 2026-02-27

### 🚀 Major Download System Upgrade

- Introduced brand-new queue-based download architecture
- Multi-item download queue inside Download tab
- Per-item progress bars
- Per-item cancel support
- Overall download progress summary bar
- Live speed + ETA display per video

### 📋 Inline Playlist Panel (New)

- Playlist auto-detection in Download tab
- Inline playlist item fetching
- Select / Deselect controls
- Add selected playlist items directly to queue
- Format & max resolution selection before adding

### 🎯 UX Improvements

- Resolution selector per queued video
- Dynamic file size estimation updates
- Cleaner progress rendering without full UI re-render
- Better error message sanitization from yt-dlp
- Improved queue summary display

### 🧠 Stability & Architecture

- Thread-safe per-item progress updates
- Reduced UI redraw overhead during downloads
- Improved cancellation handling per queue item
- Better background thread synchronization
- Improved history write consistency

---

## [1.3.0] - 2026-02-19

### 🚀 Major UI & Experience Upgrade

- Fully refined Windows 11 custom titlebar:
  - Native drag behavior
  - Proper maximize / restore animations
  - Rounded corner integration
  - Improved light theme contrast (fixed white icons issue)
- Enhanced Mica effect synchronization with theme switching
- Improved window animation transitions (minimize / restore)

### 📥 Download Enhancements

- Improved single download progress synchronization
- Better UI state reset after completion
- Improved playlist incremental rendering performance
- Optimized background thread usage with executor fallback

### 🧠 Architecture Improvements

- Better deferred executable checks to improve startup time
- Safer thumbnail rendering pipeline
- Improved history loading delay logic
- Improved thread-safe UI queue handling
- More consistent state cleanup during shutdown

### 🎨 UI Polish

- Better spinner overlay positioning
- Consistent rounded corners across all dialogs
- Improved dropdown rendering
- Cleaner progress bar styling
- Improved light/dark theme switching consistency

### 🔒 Stability Improvements

- Safer background thread handling
- Reduced race-condition edge cases
- Improved process cancellation handling
- More resilient playlist fetch logic

---

## [1.2.9] - 2026-02-18

### 🚀 Stability & Architecture Improvements

- Added `run_subprocess_safe()` for consistent, hidden subprocess execution.
- Improved atomic JSON write locking with timeout fallback logging.
- Hardened `safe_ui_call()` to prevent UI race-condition crashes.
- Improved graceful shutdown logic (executor + temp cleanup).
- More reliable output file detection after downloads.
- Improved disk space pre-check validation.

### 📥 Download Flow Improvements

- Batch downloads:
  - Improved per-item completion tracking.
  - Better fallback output path detection.
  - Cleaner structured history entries.
- Playlist sequential downloads now more stable.
- Pause/Resume state handling improved.

### 🖼 Thumbnail & Media Enhancements

- Smarter YouTube thumbnail resolution fallback:
  - `maxresdefault` → `sddefault` → `hqdefault` → `mqdefault`
- Improved thumbnail caching in History tab.
- Safer FFmpeg atomic replacement logic when embedding thumbnails.

### 🎨 UI & UX Improvements

- Improved spinner overlay positioning and rounding.
- Optimized titlebar icon loading (deferred PNG load).
- Better playlist overall progress placement.
- Consistent rounded corners across menus.
- Instant theme switching from Settings tab.

### 🔔 Notifications

- Improved thread-safe toast wrapper.
- Hardened Windows native notification integration.

---

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