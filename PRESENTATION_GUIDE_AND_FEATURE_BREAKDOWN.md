# 🎬 ReelForge AI: AI-Driven Video Editing Platform Powered by OpenMontage

> **Executive Summary for Presentation:**  
> ReelForge AI is a multimodal, agentic video production system that transforms raw, unedited footage and images into polished, viral-ready social media reels and podcasts. At its core, the platform integrates the **OpenMontage** video synthesis and composition architecture alongside a custom Computer Vision quality guard, high-speed Multimodal VLMs, and an intelligent beat-sync audio engine.

---

## 🏗️ 1. High-Level System Architecture & OpenMontage Integration

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND CLIENT                                │
│                     React 18 + Vite + TailwindCSS + Remotion                │
│       (Interactive Filmstrip, Story Approval, Vibe & Template Selector)     │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ HTTP / REST & WebSockets
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            BACKEND API & QUEUE                              │
│                    FastAPI + PostgreSQL + Redis + MinIO S3                  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Async Celery Task Queue
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AI PIPELINE & OPENMONTAGE CORE ENGINE                    │
│                                                                             │
│  ┌─────────────────────────┐             ┌───────────────────────────────┐  │
│  │   Computer Vision &     │             │    Multi-Modal Intelligence   │  │
│  │   Quality Guard         │             │    & Narrative Planning       │  │
│  │  • Laplacian Variance   ├────────────►│  • NVIDIA NIM (Nemotron)      │  │
│  │  • Farneback Opt Flow   │             │  • OpenRouter Flash Models    │  │
│  │  • Auto-Rejection       │             │  • Jaccard Deduplication      │  │
│  └─────────────────────────┘             └──────────────┬────────────────┘  │
│                                                         │                   │
│                                                         ▼                   │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                     OPENMONTAGE PRODUCTION ENGINE                     │  │
│  │                                                                       │  │
│  │  1. Scene Plan & Storyboard Synthesis (`generate_reel.py`)           │  │
│  │  2. Remotion Composer Core (`remotion-composer`)                      │  │
│  │     - Code-driven transitions (zoom_dissolve, wipes, crossfades)      │  │
│  │     - Dynamic Aspect Standardization (1080×1920 9:16 vertical)        │  │
│  │  3. Agentic Creative Skill Directives (`skills/`)                     │  │
│  │     - Color grading, sound design, and viral caption typography       │  │
│  │  4. Dynamic Density Beat-Sync & Audio Resampling (`librosa` + FFmpeg) │  │
│  │     - Climax / drop alignment, -14 LUFS loudness normalization        │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          FINAL RENDERED ARTIFACTS                           │
│              1080×1920 MP4 Highlight Reel + Synced Subtitles + BGM          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🧩 2. How OpenMontage is Used as the Core Video Editing Engine

In our platform, **OpenMontage** serves as the **central rendering orchestrator and creative director**. Specifically, we utilize OpenMontage in **4 key areas**:

### A. Scene Planning & Storyboard Synthesis (`OpenMontage/generate_reel.py`)
* **Role:** Translates raw timeline segments and LLM vision tags into a unified, executable movie storyboard (`my_reel.json`).
* **What it does:** Organizes the video into narrative phases (**Hook** $\rightarrow$ **Build-up** $\rightarrow$ **Climax / Payoff**), assigning exact timestamps, transition types, and layer depths.

### B. Remotion Video Composition Engine (`OpenMontage/remotion-composer`)
* **Role:** Programmatic, code-driven video editing.
* **What it does:** Instead of static linear cutting, the Remotion engine dynamically compiles React components into video frames. It executes high-fidelity transformations:
  * **Dynamic Crossfades & Dissolves:** Smooth 0.4s `zoom_dissolve` and `xfade` blends between scenes.
  * **Aspect Ratio Standardization:** Automatically detects source dimensions and maps mixed 16:9, 4:3, or portrait media onto a unified **1080×1920 (9:16)** frame with zero aspect distortion.

### C. Agentic Creative Skill Registry (`OpenMontage/skills/`)
* **Role:** Embedded AI production knowledge.
* **What it does:** Provides the rules and heuristics for:
  * **Color Grading (`skills/core/color-grading.md`):** Color space preservation (`yuv420p`) to eliminate black frames between cuts.
  * **Sound Design (`skills/creative/sound-design.md`):** Audio ducking, ambient fading, and loop smoothing.
  * **Typography & Viral Captions (`skills/creative/typography.md`):** Social-first subtitle placement (`Line 1 | Line 2` format).

### D. Audio-Video Synchronization & Normalization
* **Role:** Timeline integrity and broadcast compliance.
* **What it does:** Uses OpenMontage's audio drift prevention algorithms (`-fflags +genpts -af aresample=async=1`) and normalizes audio to `-14 LUFS` for Instagram Reels / YouTube Shorts.

---

## 🚀 3. Complete Feature Breakdown & Toolstack

Below is the step-by-step breakdown of every feature in ReelForge AI, what it accomplishes, and the exact underlying tools used:

---

### Feature 1: Intelligent Media Ingestion & Multi-Format Support
* **Description:** Users can upload any mix of raw camera clips (MP4, MOV), phone footage, and high-resolution still images (JPG, PNG).
* **Under-the-Hood Workflow:**
  1. Files are uploaded via FastAPI asynchronous chunked streams.
  2. Presigned URLs and metadata are cataloged in **PostgreSQL**.
  3. Raw assets are stored in **MinIO S3 Object Storage**.
* **Tools Used:** `FastAPI`, `PostgreSQL 15`, `MinIO`, `SQLAlchemy`, `Docker`.

---

### Feature 2: Computer Vision Quality & Motion Guard (Optical Flow)
* **Description:** Automatically filters out blurry, out-of-focus, or shaky camera frames before sending them to the AI, saving computation and ensuring cinematic quality.
* **Under-the-Hood Workflow:**
  1. **Frame Downsampling:** Frames are extracted and resized to 360px width for 10–50x faster processing.
  2. **Laplacian Variance ($\text{Var}(\nabla^2 I)$):** Evaluates frame sharpness. Segments with average blur score $< 45.0$ are automatically dropped.
  3. **Farneback Dense Optical Flow:** Tracks pixel motion vectors between frames to classify camera motion:
     * `SETTLED` (Stabilized shots) $\rightarrow$ Prioritized for hooks.
     * `LINEAR_FORWARD` (Smooth walking motion) $\rightarrow$ Used for pacing.
     * `WHIP_PAN` & `CHAOTIC` (Shaky/erratic motion) $\rightarrow$ Automatically rejected.
* **Tools Used:** `OpenCV (cv2)`, `Pillow (PIL)`, `NumPy`.

---

### Feature 3: Multimodal Vision AI & Cultural Element Tagging
* **Description:** Deeply understands the visual context, emotions, and specific cultural themes present in the video (e.g., temples, weddings, sports, celebrations).
* **Under-the-Hood Workflow:**
  1. Videos $>30\text{s}$ are segmented into 45-second sliding windows.
  2. 4 representative keyframes per chunk are converted to base64 payloads.
  3. Prompts are dispatched to Vision-Language Models (VLMs) to identify the best action windows and emotional peaks.
  4. A **Reverse-Scanning Balanced Bracket JSON Parser** strips reasoning/thinking tokens and repairs schemas on the fly.
* **Tools Used:** `NVIDIA NIM` (`nemotron-3-nano-omni-30b`), `OpenRouter` (`Qwen-2.5-VL`, `Gemini Flash`), `httpx`.

---

### Feature 4: Human-in-the-Loop Storytelling Review
* **Description:** Gives creators control by proposing an AI-generated narrative arc that can be reviewed, refined, or rewritten before final video rendering.
* **Under-the-Hood Workflow:**
  1. The LLM synthesizes all candidate clips into a 3-act story (Hook $\rightarrow$ Body $\rightarrow$ Climax).
  2. The Celery worker updates the job status to `STORY_PROPOSED`.
  3. The React UI opens a glassmorphic editor displaying the story.
  4. The user approves or modifies the story, which immediately resumes the render pipeline.
* **Tools Used:** `Celery`, `Redis`, `React 18`, `TailwindCSS`.

---

### Feature 5: Smart Semantic Deduplication & Cut Budgeting
* **Description:** Prevents repetitive or monotonous edits by ensuring scene diversity.
* **Under-the-Hood Workflow:**
  1. **Adaptive Clip Limits:** Short videos get max 2 clips; long videos get max 3 clips.
  2. **Gap Enforcement:** Enforces a mandatory minimum 2.0-second time gap between clips taken from the same source file.
  3. **Jaccard Semantic Filter:** Discards candidate clips that share $>60\%$ subject similarity or $>30\%$ description keyword overlap.
* **Tools Used:** `Python math / set logic`, `OpenRouter Text LLMs`.

---

### Feature 6: Indian Reels & Vibe-Matched Music Engine
* **Description:** Dynamically sources, matches, and synchronizes background scores based on video vibe (Devotional, Romantic, Energetic, Travel, Garba).
* **Under-the-Hood Workflow:**
  * **Mode 1 (AI Curated Catalog):** Matches visual tags to curated Bollywood and regional tracks (e.g., *Deva Deva*, *Kaun Hai Woh*, *Ilahi*, *Gajanana*).
  * **Mode 2 (Custom Song via `yt-dlp`):** User types any song name $\rightarrow$ system automatically searches YouTube, extracts high-bitrate MP3 audio, and caches it in MinIO.
  * **Mode 3 (Suno AI Generation):** Prompts Suno AI API to generate an original bespoke composition based on video mood.
* **Tools Used:** `yt-dlp`, `Suno AI API`, `MinIO Cache`, `Spotipy / Music Catalog`.

---

### Feature 7: Dynamic Density Beat-Sync & Waveform Engine
* **Description:** Analyzes musical pacing to synchronize video cuts with musical drops and rhythm peaks.
* **Under-the-Hood Workflow:**
  1. **Librosa Analysis:** Computes RMS energy, onset strength, and spectral novelty curves.
  2. **Climax Detection:** Locates the song's primary chorus or beat drop and trims the audio so the visual climax coincides with the musical drop.
  3. **Audio Pacing:** Calculates tempo (BPM) to space clip cuts smoothly and prevents rapid "machine-gun" cutting.
* **Tools Used:** `librosa`, `scipy`, `numpy`, `matplotlib` (waveform visualization).

---

### Feature 8: Automated Montage Assembly & Transitions (OpenMontage + FFmpeg)
* **Description:** High-speed rendering pipeline that compiles clips, dynamic transitions, and mixed audio into the final MP4.
* **Under-the-Hood Workflow:**
  1. **Subsecond Trimming:** Clips are trimmed with zero timestamp offset errors (`-avoid_negative_ts make_zero`).
  2. **Dynamic `xfade` Transitions:** Seamlessly weaves clips using `zoom_dissolve` and `fade` transitions (0.4s duration).
  3. **Audio Mixing:** Blends background music, applies a smooth 1.5s fade-out, and normalizes loudness to `-14 LUFS`.
  4. **MinIO Upload & S3 Delivery:** Saves the finished reel for instant streaming and download in the React UI.
* **Tools Used:** `FFmpeg`, `ffprobe`, `OpenMontage Remotion Bridge`, `MinIO`.

---

### Feature 9: Specialized AI Podcast & Talking-Head Processor
* **Description:** Converts long-form talking-head recordings into dynamic shorts with animated subtitles and punchline auto-zooms.
* **Under-the-Hood Workflow:**
  1. **Speech-to-Text:** Local Whisper engine generates word-level timestamps with zero API costs.
  2. **Smart Subtitles:** Groups spoken words into 3–4 word punchy lines burned into video via FFmpeg `drawtext`.
  3. **Moment Detection & Auto-Zoom:** An LLM detects key statistics and jokes, triggering smooth `zoompan` camera zooms ($1.0\times \rightarrow 1.3\times$).
* **Tools Used:** `faster-whisper` / `openai-whisper`, `FFmpeg zoompan & drawtext`, `OpenRouter LLMs`.

---

## 📊 Summary Table for Quick Presentation Slides

| Pipeline Stage | What it Does | Core Tools & Frameworks |
| :--- | :--- | :--- |
| **1. Ingestion** | Multi-file upload, S3 caching, project state | `React`, `FastAPI`, `MinIO`, `PostgreSQL` |
| **2. Quality Guard** | Blur rejection & camera motion classification | `OpenCV (Laplacian + Farneback Optical Flow)` |
| **3. Vision AI** | Frame analysis, vibe tagging, cultural detection | `NVIDIA NIM Nemotron`, `OpenRouter VLMs` |
| **4. Storyboard** | 3-act narrative script & human approval review | `OpenRouter Text LLMs`, `React UI` |
| **5. Deduplication** | Removes repetitive shots & optimizes clip pacing | `Jaccard Similarity Algorithms` |
| **6. Music Engine** | Vibe-matching, YouTube song retrieval, Suno AI | `yt-dlp`, `Suno AI`, `Curated Music Catalog` |
| **7. Beat Sync** | Onset detection & drop synchronization | `Librosa`, `SciPy`, `NumPy` |
| **8. Video Assembly** | Subsecond cuts, `zoom_dissolve` xfades, audio mixing | **`OpenMontage`**, **`Remotion`**, **`FFmpeg`** |
| **9. Podcast Engine** | Word-level animated captions & dynamic auto-zoom | `faster-whisper`, `FFmpeg zoompan/drawtext` |
