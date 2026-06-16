# AI Video Analyzer & Highlight Reel Editor 🎬

An intelligent video processing pipeline and web editor that automatically analyzes raw video clips, extracts the most compelling cinematic moments using Vision AI, and compiles them into a polished highlight reel.

---

## 🌟 Key Features

### 🧠 Split-Routing AI Engine
*   **Dual API Orchestration**: Leverages **NVIDIA NIM** (`build.nvidia.com`) with `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` for visual frame analysis, and **OpenRouter** text models (like `openai/gpt-oss-120b` or fallbacks) for high-speed narrative sequencing and BGM selection.
*   **Prompt Robustness**: Dynamically adjusts prompting templates based on whether the user provides custom editing directives, bypassing default location grouping or chronological sorting when instructions demand it.
*   **Reverse-Scanning JSON Parser**: Employs a self-correcting balanced bracket matcher scanning in reverse to clean reasoning leaks and extract the final valid JSON block from LLM responses. It also triggers an automatic LLM schema repair fallback on corrupt payloads.

### 🔍 Optical Flow & Multi-Dimensional Quality Analysis
*   **10-50x Faster Processing**: Downsamples video frames to a standard 360px width for near-instant blur (Laplacian variance) and motion (Farneback optical flow) checks.
*   **Motion Classification**: Categorizes camera motion into `SETTLED` (stabilized), `LINEAR_FORWARD` (walking bob), `DISTANT_WIDE` (stable far subject), `NORMAL`, `WHIP_PAN`, and `CHAOTIC` (shakes). Whip pans and chaotic frames are rejected.
*   **Programmatic Blur Guard**: Rejects clip candidates that fail the average raw blur threshold (avg blur < 45.0) to prevent AI hallucinations on out-of-focus footage.
*   **Quality-Guided Fallbacks**: Automatically falls back to the sharpest, most settled 3.0s window using computed motion data if the Vision API fails or times out.

### ✂️ Smart Timeline Deduplication
*   **Adaptive Clip Allowances**: Restricts short videos (< 30s) to a max of 2 clips, and longer videos to a max of 3 clips, ensuring diverse shots.
*   **Overlap & Gap Constraints**: Enforces a minimum **2.0-second time gap** between highlights from the same source and rejects overlapping segments (overlap ratio > 0.3).
*   **Semantic Similarity Filtering**: Prevents repetitive shots of the same setting. Clips with identical location tags are discarded if they share a Jaccard subject overlap $\ge$ 60% or a description keyword overlap $\ge$ 30%.

### 🎵 Indian Reels BGM Heuristics & Music Engine
*   **Instrumental vs. Lyrical Modes**: Automatically adapts to instrumental (lofi, acoustic, classical, pop, edm) or lyrical soundtracks.
*   **Theme Detection**: Categorizes footage into **Devotional/Spiritual**, **Temple Travel**, **Travel/Lifestyle**, or **Generic** based on VLM visual labels (e.g. searching for agni, aarti, mandir, ganga, sadhu, diya, bells, etc.).
*   **Curated Bollywood Song Pools**: Automatically selects matching viral tracks (e.g., *Deva Deva*, *Namo Namo*, *Ilahi*, *Kun Faya Kun*, *Ram Siya Ram*, *Safar*, *Tauba Tauba*) based on VLM-detected mood and theme.
*   **Multi-Source Audio Resolver**: Fetches music dynamically via YouTube downloads (`yt_dlp` with cache matching), Pixabay, Suno AI custom generation, or local libraries.

### 📝 Viral Captions & Subtitles
*   **Two-Line Viral Split**: Formats captions using the viral `Line 1 | Line 2` structure, evoking feeling over dry visual description.
*   **Caption Scopes**: Supports per-clip captions or a single global caption placed at the top of the reel.
*   **Subtitles & Subsecond Trimming**: Automatically generates synced `.srt` files and handles subsecond trims, normalizing audio outputs to a standard `-14 LUFS` loudness.

### 🖥️ Cinematic Editor UI
*   **Waitress Web Server**: Serves a premium cinematic dark-themed web interface powered by a production Waitress WSGI server.
*   **Interactive Filmstrip**: Truncate/extend segments in a visual timeline, perform manual segment additions, drag-and-drop elements, preview audio/videos, and stream real-time logs.
*   **Remotion Integration**: Integrates directly with a React-based **Remotion Composer** to apply transitions (cuts, fades, dissolves, zoom ins/outs) and hot-sync edits instantly into a unified movie config (`my_reel.json`).

---

## 🛠️ Tech Stack

*   **Backend**: Python 3, Flask, Waitress
*   **Video Processing**: FFmpeg, FFprobe, OpenCV (`cv2`)
*   **Frontend**: HTML5, CSS3 (cinematic glassmorphism variables), JavaScript
*   **Integration Engines**: Remotion Composer (React / TypeScript), `yt_dlp`
*   **AI Models**: NVIDIA NIM (Nemotron reasoning engine), OpenRouter (GPT/Llama text models)

---

## 📂 Project Structure

*   [main.py](file:///Users/priyanshimodi/Documents/projects/TSC/video_analyzer/main.py): Sets up the environment, logs to `analyzer.log`, and boots the Waitress server on `http://127.0.0.1:5050`.
*   [pipeline.py](file:///Users/priyanshimodi/Documents/projects/TSC/video_analyzer/pipeline.py): The core orchestrator. Downsamples frames, runs parallel quality pipelines, applies programmatic guards, resolves alignment scores, and runs story sequencing.
*   [quality.py](file:///Users/priyanshimodi/Documents/projects/TSC/video_analyzer/quality.py): Computes blur/Farneback optical flow and runs the motion type classifier.
*   [stitch.py](file:///Users/priyanshimodi/Documents/projects/TSC/video_analyzer/stitch.py): FFmpeg stitching helper that detects aspect ratios and preserves color spaces.
*   [llm.py](file:///Users/priyanshimodi/Documents/projects/TSC/video_analyzer/llm.py): Handles multithreaded requests to NVIDIA NIM & OpenRouter.
*   [config.py](file:///Users/priyanshimodi/Documents/projects/TSC/video_analyzer/config.py): Configures models, fallbacks, rate limits, and thresholds.
*   [OpenMontage/generate_reel.py](file:///Users/priyanshimodi/Documents/projects/TSC/video_analyzer/OpenMontage/generate_reel.py): Coordinates the generation of assets (audio BGM, voiceovers, subtitle SRTs) and compiles the final cinematic reel via Remotion/FFmpeg.
*   [editor_ui/](file:///Users/priyanshimodi/Documents/projects/TSC/video_analyzer/editor_ui):
    *   [app.py](file:///Users/priyanshimodi/Documents/projects/TSC/video_analyzer/editor_ui/app.py): Flask routes, API endpoints, manual segment triggers, and hot-syncing.
    *   [templates/editor.html](file:///Users/priyanshimodi/Documents/projects/TSC/video_analyzer/editor_ui/templates/editor.html): Dark-themed timeline editor.
    *   [static/style.css](file:///Users/priyanshimodi/Documents/projects/TSC/video_analyzer/editor_ui/static/style.css): Custom CSS styles.

---

## 🚀 Setup & Installation

1.  **Prerequisites**: Install `ffmpeg` on your system:
    ```bash
    # macOS
    brew install ffmpeg
    ```
2.  **Environment Setup**: Create a `.env` file in the root directory:
    ```env
    NVIDIA_API_KEY=your_nvidia_nim_api_key_here
    OPENROUTER_API_KEY=your_openrouter_api_key_here
    ```
3.  **Install Python Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

---

## 💻 How to Run

Launch the application:
```bash
python main.py
```
Open `http://127.0.0.1:5050` in your web browser. Upload videos in `input_videos`, run the AI analyzer to generate timeline segments, apply post-processing adjustments (music, captions, transitions), and render the final highlight reel!
