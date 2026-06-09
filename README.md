# AI Video Analyzer & Highlight Reel Editor 🎬

An intelligent video processing pipeline and web editor that automatically analyzes raw video clips, extracts the most compelling cinematic moments using Vision AI, and stitches them into a seamless highlight reel.

---

## 🌟 Key Features

*   **Split-Routing AI Engine**: Uses high-performance **NVIDIA NIM** (`build.nvidia.com`) for visual frame analysis and **OpenRouter** for cheap and fast story-text sequencing.
*   **Intelligent Vision Analysis**: Leverages `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` with an expanded `max_tokens` limit of **1200** to prevent verbose JSON responses from getting truncated.
*   **Split-Path Directives Prompting**: Dynamically serves two separate prompt templates depending on whether the user provided **Custom Editing Instructions** or not. When directives are provided, standard rules (like chronological pre-sorting or location grouping) are bypassed to prevent prompt rule contradictions.
*   **Uploaded File Order Option**: Adds a toggle to skip the LLM story sequencing and order the highlights strictly by the uploaded file order (alphabetically by filename), while still leveraging the VLM to extract the best/highest-quality segments from each video.
*   **Robust self-correcting JSON Parser**: Uses a balanced bracket matcher scanning in reverse to handle cases where the model outputs reasoning text or self-corrections (extracting the last valid JSON block).
*   **Audit-Ready Prompt Logging**: Automatically records the complete **`INPUT PROMPT`** (including directives) alongside the model response in local logs (e.g., `story_order_attempt1.txt`) for easy verification.
*   **Resolution Auto-Detection**: Automatically detects the aspect ratio of your clips. If landscape (horizontal) footage predominates, it builds the reel in **1920×1080 (widescreen)** format to prevent side-cropping; otherwise, it outputs in **1080×1920 (portrait)**.
*   **Smart Timeline Deduplication**: 
    *   Enforces a minimum **3.0-second time gap** between clips from the same source video to prevent repeating identical shots.
    *   Dynamically adjusts clip allowances (up to **3 clips** for videos longer than 30s) to preserve maximum variety.
*   **Narrative AI Director**: Sequences clips into a cohesive emotional arc (Hook $\rightarrow$ Build $\rightarrow$ Payoff) and generates detailed "Director's Notes" explaining the editing choices.
*   **Visual Filmstrip Editor**: Features a premium dark-themed web interface with a custom filmstrip trimmer, live video scrubbing, timeline drag-and-drop, and a **Quick-Add (`+` / `✓`)** button to immediately insert segments from the library.
*   **Auto-Stitching Engine**: Streamlined integration with `ffmpeg` to trim, re-encode, normalize, and concatenate segments into a high-quality highlight reel (`final_highlight_reel.mp4`).

---

## 🛠️ Tech Stack

*   **Backend**: Python, Flask, Waitress (Production WSGI Server)
*   **Video Processing**: FFmpeg, FFprobe, OpenCV (via `subprocess` and `cv2` APIs)
*   **AI Integration**: NVIDIA NIM API (Vision), OpenRouter API (Story text/reasoning)
*   **Frontend**: Vanilla HTML5, CSS3 (Glassmorphism & premium CSS variable tokens), JavaScript

---

## 📂 Project Structure & Code

### `main.py`
The main entry point. Sets up the environment, configures file logging to `analyzer.log`, and boots up the production-grade Waitress server on `http://127.0.0.1:5050`.

### `pipeline.py`
The core AI orchestration engine. Manages frame extraction, calls visual analysis models, merges chunked data, executes deduplication/time-gap logic, and sequences final clips.

### `stitch.py`
The FFmpeg editing wrapper. Handles aspect-ratio auto-detection, sub-second trimming, video normalization (`yuv420p` color space preservation), and GenPTS audio alignment.

### `llm.py`
Manages connections, tokens, routing, and timeouts to NVIDIA NIM and OpenRouter servers with auto-recovery logic.

### `prompts.py`
Contains the strict travel-reel instructions, visual heuristics, and JSON schemas used to guide the LLM's editing choices.

### `editor_ui/`
*   `app.py`: Flask controller serving HTML templates and API endpoints.
*   `templates/editor.html`: Advanced web editing timeline with filmstrip trimmer, preview player, library panel, and status monitors.
*   `static/style.css`: Modern cinematic glassmorphism styles and color tokens.

---

## 🚀 Setup & Installation

1.  **Prerequisites**: Install `ffmpeg` on your system:
    ```bash
    # macOS
    brew install ffmpeg
    ```
2.  **Environment Variables**: Create a `.env` file in the root directory:
    ```env
    NVIDIA_API_KEY=your_nvidia_nim_api_key_here
    OPENROUTER_API_KEY=your_openrouter_api_key_here
    ```
3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

---

## 💻 How to Run

Start the server by running:
```bash
python main.py
```
The application will automatically open in your default web browser at `http://127.0.0.1:5050`. Upload your raw videos, let the AI analyze them, edit the timeline, and build your final highlight reel!
