
# 📖 Webtoon Reader (Flask)

A **self-hosted, multi-user webtoon / comic reader** built with **Python + Flask**, designed for **local libraries**, **CBZ/CBR archives**, and **mobile-first reading**.

This project focuses on:
- performance
- correctness
- resumable reading
- long-term maintainability
- real-world archive support

---

## ✨ Features

### 📚 Library & Content
- Library stored on disk as:
```
library/
└── Title/
├───── Episode/
│      └───── image files (jpg / png / webp)
├───── Episode.cbz
└───── Episode.cbr
```

- Supports **folder-based episodes**
- Supports **CBZ (ZIP) archives**
- Supports **CBR (RAR) archives**
- Uses **real `unrar` (RARLAB)** for full Unicode & solid archive support
- Mixed content allowed (folders + archives)
- Scan results stored in database (no repeated HDD scans)

---

### 🔍 Scanning
- **Background scanning** (non-blocking)
- Two scan modes:
- **Regular scan**
  - Fast
  - Detects only new titles & episodes
  - Safe for frequent runs / automation
- **Thorough scan**
  - Full reindex
  - Rebuilds episode images
  - Repairs metadata
- Scan progress displayed in UI
- Scan trigger:
- Web UI (admin)
- API endpoint (no cookie, suitable for `curl` / automation)
- Incremental & deterministic (no `os.walk`)

---

### 👤 Users & Authentication
- Multi-user support
- Secure password hashing
- User roles:
- **Admin**
- **Regular user**
- First-run behavior:
- If no user exists, an admin registration link is generated
- Admin features:
- Create users
- Enable / disable users
- Grant admin privileges
- One-time **registration link with nonce** for new users
- User preference page (password change)

---

### 📖 Reading Experience
- Vertical webtoon reading (continuous scroll)
- No gaps between images
- **Lazy loading** of images (memory-efficient)
- Infinite scrolling
- Mobile-optimized UI (auto-detected)
- Click navigation:
- Tap upper half → scroll up
- Tap lower half → scroll down
- Next episode button at end of episode

---

### 🔖 Progress & Resume
- Per-user reading progress
- Resume stored **per episode**
- Resume logic based on **image index**, not pixels
- Always resumes at **start of last read image**
- Scroll position restored automatically
- Resume badge shown in episode list
- Episode card dims when reading has started
- Episode marked as read when fully completed
- Progress saved during scrolling (debounced)

---

### 🧭 Navigation
- Always-visible **sticky breadcrumb**
- Breadcrumb features:
- Jump between:
  - Home → Title → Episode
- Previous / next episode buttons
- Scan progress indicator
- Theme toggle
- Logout button
- Admin actions (user management)
- Breadcrumb styled for both light & dark themes

---

### 🎨 UI / UX
- Light & Dark themes
- Theme preference stored in browser
- Card-based UI:
- Titles: rounded square cards
- Episodes: horizontal cards
- Episode cards include:
- Episode number (human-sorted)
- Episode name
- **80×80 thumbnail** (first page)
- Read / resume indicators
- Clean mobile and responsive layout

---

### ⚙️ Availability & Moderation (Future-proofed)
Database fields added for:
- `User.enabled`
- `Title.available`
- `Episode.available`
- `EpisodeImage.available`

(Currently default to `true`, ready for future content moderation UI.)

---

### 🌐 Deployment & Infrastructure
- Flask backend
- SQLAlchemy ORM
- SQLite (default, easily replaceable)
- Docker-ready:
- `Dockerfile`
- `docker-compose.yml`
- Runs on `0.0.0.0`
- Reverse-proxy friendly (Nginx sub-folder support)
- Works behind `/subpath` using proper URL handling
- Logs application & scan activity
- Werkzeug logs silenced / adjustable

---

### 📦 Archive Handling (Important)
- **CBZ**: streamed via Python `zipfile`
- **CBR**: streamed via native `unrar p`
- Supports:
  - Unicode filenames (UTF-16)
  - Solid archives
  - Large images
- No extraction to disk
- No temporary files
- Low memory usage
- Reliable streaming

---

## 🚀 Roadmap Ideas

* Admin UI for content availability
* Search (title / episode)
* Per-title rescan
* Archive integrity checks
* `.7z` support
* PDF episodes
* Reading statistics
* OPDS / API export

---

## 🧑‍💻 Philosophy

This project aims to be:

* simple to self-host
* fast on large libraries
* correct with real-world data
* pleasant to read on mobile
* easy to extend without refactors

---

Enjoy reading 📖✨
