# 🧾 Changelog

All notable changes to **Clipster** are documented here.

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

---

## 📦 v1.2.3 — *Refined, Reliable, and Polished* (November 2025)

### Highlights
- ⚡ Instant Startup (3× faster)
- 🧩 ThreadPool stability and atomic JSON writes
- 💾 Disk-space warnings
- 🧾 Improved metadata fetching
- 🎨 Mica titlebar and dynamic theming

---

> “Fetch. Download. Enjoy.” — **Clipster**
