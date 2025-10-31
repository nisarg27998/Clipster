# 🎬 Clipster

**Clipster** is a modern, elegant YouTube downloader for Windows — powered by **yt-dlp**, **FFmpeg**, and a sleek **CustomTkinter GUI**.

> “Fetch. Download. Enjoy.”

---

## ✨ Features

- 🎞️ **Single / Batch / Playlist** downloads
- 🖼️ **Automatic thumbnail embedding**
- 🧱 **Thread-safe architecture** — No UI freezes, no crashes
- 💾 **Persistent settings and history**
- ⚙️ **Format & resolution selection** (MP4, MKV, WEBM, M4A)
- 🎨 **Windows 11 Mica interface**
- 🌙 **Dark / Light theme support**
- 🔔 **Toast notifications** for background updates
- 🔄 **Auto-update check** from GitHub

---

## 🧠 New in v1.2.2 — *Stable & Thread-Safe Core*

- 🔒 Atomic and thread-safe **settings/history writes**
- 🧵 Background operations managed via **ThreadPoolExecutor**
- 🪶 Smarter, cleaner **shutdown logic**
- 🧩 Robust **yt-dlp** and **FFmpeg** subprocess handling
- 🧾 Optional **debug logging mode**
- 🪄 Unified **UI-safe event handling** via internal queue

---

## 📦 Installation

No setup required — just download the latest `.exe` release:

👉 [**Clipster Releases on GitHub**](https://github.com/nisarg27998/Clipster/releases)

**Included executables:**
- `yt-dlp.exe`
- `ffmpeg.exe`
- `ffprobe.exe`
- `ffplay.exe`

> All are bundled inside Clipster.exe — no external dependencies needed.

---

## ⚙️ System Requirements
- Windows 10 / 11 (64-bit)
- Internet connection
- GPU-accelerated UI (recommended)

---

## 🗺️ Roadmap

| Version | Focus | Highlights |
|----------|--------|------------|
| **v1.2.3** | UX Polish | Queue management, retry logic, smart metadata caching |
| **v1.3.0** | Integrations | Subtitle download, multi-format presets |
| **v1.4.0** | AI Assist | Smart name cleanup & auto-tagging |

---

## 🧩 Tech Stack

- **Language:** Python 3.13  
- **GUI:** [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)  
- **Downloader:** [yt-dlp](https://github.com/yt-dlp/yt-dlp)  
- **Media Tools:** FFmpeg suite  
- **Packaging:** PyInstaller  

---

## 🧾 License

Licensed under the **MIT License**.  
Copyright © 2025  
Developed by **Nisarg Panchal**

---

> 🧡 A passion project for speed, stability, and simplicity.
