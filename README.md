# 🎬 Clipster

**Clipster** is a modern **YouTube downloader for Windows**, built with **Python 3.13** and **CustomTkinter**, designed for simplicity, speed, and style.

It allows you to download single videos, playlists, or batches — all with a sleek UI and smart automation.

---

## 🚀 Features

### 🧠 Smart Download System
- One-click video and playlist downloads  
- Auto-selects best quality (video + audio merge)  
- Playlist & batch download support  
- Built-in progress tracking  
- Intelligent filename handling  
- Per-video and per-playlist progress indicators  
- Resume incomplete downloads *(coming soon)*

### 🎨 Modern Interface
- Built using **CustomTkinter** for a clean, modern Windows look  
- Dark, rounded, and responsive UI  
- Animated transitions and drag indicators  
- Toast notifications for status and completion  
- Compact progress HUD *(coming soon)*  

### 🧰 Power Tools
- FFmpeg-based merging and conversion  
- Supports MP4, MKV, and MP3 formats  
- Download history with thumbnails  
- Context actions (Reopen / Redownload / Delete) *(planned)*  
- Audio-only extraction *(coming soon)*

---

## 📦 Installation

You don’t need Python installed!  
Just download the latest `.exe` from the [**Releases** section](https://github.com/yourusername/Clipster/releases) and run it directly.

---

## 🧩 Requirements

✅ None — the app comes fully packaged.  
All dependencies (FFmpeg, yt-dlp, etc.) are pre-bundled inside the executable.

---

## 🐞 Bug Fixes (v1.2.1)
- Fixed: App crashing on invalid URLs  
- Fixed: Playlist progress bar not updating properly  
- Improved: Toast responsiveness and animations  
- Improved: Error handling during downloads  

---

## 🧭 Roadmap

### **v1.3 – Smart Downloads & Stability**
🧠 *Focus:* Intelligent automation and bug fixes  
- Auto-select best format (max resolution)  
- Auto-create subfolders per playlist  
- Resume interrupted downloads  
- Batch resolution limit (≤1080p, etc.)  
- Auto-rename invalid filenames  
- Sequential download queue  
- 🐞 Fix: Batch download issue  
- 🐞 Fix: Long video names cut off in Single Download  

---

### **v1.4 – UI / UX Overhaul**
🎨 *Focus:* Modern look and better usability  
- Modern progress HUD overlay with ETA  
- In-app toast center (view last 5 notifications)  
- Adaptive layout for small screens  
- Rounded thumbnail previews in history  
- Quick action buttons beside history items  
  - ▶️ Open in browser  
  - 🔁 Re-download  
  - 🗑️ Remove  

---

### **v1.5 – Power Tools & Automation**
🧰 *Focus:* Expanding Clipster’s capabilities  
- Audio-only extraction (MP3 / M4A) with thumbnail embed  
- Batch audio conversion (MP4 → MP3 via FFmpeg)  
- Clipboard auto-detect for YouTube URLs  
- Auto-fetch metadata on paste  
- Download completion sound/toast with thumbnail  

---

### **Future Ideas (v1.6+)**
💡 *Clipster Pro Vision*  
- Auto-update via GitHub API  
- Cloud sync for settings/history  
- Theme toggle (Light/Dark)  
- Plug-in system for other sites (Vimeo, SoundCloud)  

---

## 🧰 Tech Stack
- **Language:** Python 3.13  
- **UI Framework:** CustomTkinter  
- **Backend Tools:** yt-dlp, FFmpeg  
- **Platform:** Windows 10/11  
- **Packaging:** PyInstaller (OneFile Executable)

---

## 🧑‍💻 Developer Notes
- Store `yt-dlp.exe` and `ffmpeg.exe` in the `Assets/` folder (auto-handled in packaged build).  
- Supports drag-and-drop URLs.  
- Smooth startup animation and minimized flicker.  

---

## 📜 Changelog
See [CHANGELOG.md](./CHANGELOG.md) for a full version history.

---

## ❤️ Credits
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)  
- [FFmpeg](https://ffmpeg.org/)  
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)

---

## 📢 License
This project is licensed under the **MIT License** — free for personal and commercial use.

---

> **Clipster v1.2.1** — Smart, fast, and stylish YouTube downloader.  
> *Next milestone: v1.3 Smart Download Update 🚀*
