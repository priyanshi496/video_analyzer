# Video Analyzer & AI Montage Generator - UX & Data Flow

This document outlines the end-to-end architecture, API data flows, and the User Experience (UX) workflow for the Video Analyzer application. This is intended to be used as a master reference for frontend designers (Figma) and AI UI generators (Lovable, v0.dev, Bolt) to understand exactly how the application functions and what screens need to be designed.

## 1. High-Level Concept
The application takes raw video footage and images, analyzes their physical quality (blur/shake/motion), feeds the visual context to a multimodal LLM (NVIDIA Nemotron / OpenRouter), and autonomously edits the footage into a cohesive, music-synced "Reel" or Montage based on a chosen vibe.

---

## 2. Global State & Architecture
- **Frontend Stack**: React (Vite) + TailwindCSS.
- **Backend Stack**: FastAPI (Python) + PostgreSQL (SQLAlchemy) + MinIO (S3 Object Storage) + Celery/Redis (Background workers).
- **Authentication**: JWT token-based (Bearer). Currently handled seamlessly via Axios interceptors.

---

## 3. The User Journey (Screen by Screen)

### Screen 1: Dashboard (Project Management)
**Purpose**: Landing page where users can view their past creations or start a new video project.
**API Endpoints Involved**:
- `GET /api/v1/projects` (Fetches list of projects, including their latest thumbnails/status)
- `POST /api/v1/projects` (Creates a new empty project workspace)

**UX Flow**:
1. User sees a grid of `ProjectCards`.
2. Each card shows the project name, creation date, and a thumbnail (extracted from the first uploaded video).
3. Clicking "Create Project" automatically hits the POST endpoint and redirects the user to the Project Workspace.

### Screen 2: Project Workspace (Media Upload & Configuration)
**Purpose**: The central hub for a specific project where the user uploads raw footage and sets the creative constraints.
**API Endpoints Involved**:
- `GET /api/v1/projects/{id}` (Fetches project details)
- `GET /api/v1/projects/{id}/media` (Fetches all uploaded media assets for this project)
- `POST /api/v1/projects/{id}/media` (Multipart form upload for dragging & dropping videos/images)
- `GET /api/v1/projects/{id}/jobs/latest` (Checks if there is already an active or completed generation job for this project)

**UX Flow**:
1. **Left Panel (Media)**: A large dropzone for uploading raw MP4/MOV/JPG files. Below it, a vertical list of uploaded media showing thumbnails, filenames, and file sizes.
2. **Right Panel (Configuration)**:
   - **Vibe**: Dropdown (e.g., Cinematic, Fast-paced, Nostalgic, Hype).
   - **Music Mode**: Dropdown (AI Catalog Match, Suno Generation, Custom, None).
   - **Instrumental Only**: Checkbox.
   - **Directives**: Textarea for custom instructions (e.g., "Focus on the shots of the ocean").
3. **Action Button**: A prominent "Generate Reel" button at the bottom of the config panel.

### Screen 3: The Generation State (Progress & Processing)
**Purpose**: Keeping the user engaged while the heavy backend Celery worker processes the videos.
**API Endpoints Involved**:
- `POST /api/v1/projects/{id}/analyze` (Triggered by "Generate Reel" button. Creates the background job and returns a `job_id`).
- `GET /api/v1/jobs/{job_id}` (Polled every 3 seconds to update the progress bar and status text).

**UX Flow**:
1. When "Generate Reel" is clicked, the configuration panel is locked.
2. A status card appears showing a progress bar and the current status (`PENDING` -> `RUNNING`).
3. *Designer Note*: The backend does heavy lifting here (OpenCV frame extraction, LLM vision requests). The UI should have a beautiful, shimmering progress state to indicate active processing.

### Screen 4: The Story Review Modal (Human-in-the-Loop Checkpoint)
**Purpose**: The AI has analyzed the videos and proposed a storyline. The user must approve or edit this story before the final video is rendered.
**API Endpoints Involved**:
- `POST /api/v1/jobs/{job_id}/confirm-story` (Sends the approved/edited text back to the worker to resume rendering).

**UX Flow**:
1. The polling endpoint returns `status: STORY_PROPOSED`.
2. A massive, full-screen glassmorphic modal automatically pops up over the workspace.
3. The modal contains a large text area pre-filled with the AI's narrative arc (e.g., "The video will start with the serene ocean shots, transitioning into the fast-paced running sequence...").
4. The user can rewrite this text completely.
5. User clicks "Approve & Generate Reel". The modal closes, and the status goes back to `RUNNING` for the final FFmpeg rendering phase.

### Screen 5: Final Result & Reset
**Purpose**: Displaying the final rendered montage.
**API Endpoints Involved**:
- `GET /api/v1/jobs/{job_id}` (Polled until status is `COMPLETED` or `FAILED`).

**UX Flow**:
1. Once `COMPLETED`, a video player appears above the configuration panel showing the final, rendered montage (complete with background music).
2. The user can watch and download the video.
3. **Reset Flow**: Below the completed status, a "Configure New Reel" button appears. Clicking this clears the job status state and unlocks the configuration panel, allowing the user to change the vibe/music and trigger a brand new generation for the exact same media.

---

## 4. Advanced Future Features (For UI Designers to Prepare For)
The backend already supports these features, but they are not yet wired into the React UI. Designers should create wireframes for these components:

1. **The Interactive Timeline Editor**: 
   - *Backend*: `GET /api/v1/projects/{id}/timeline`
   - *Concept*: Instead of just showing the final video, the UI should reveal a horizontal timeline scrubber (like Premiere Pro or CapCut) showing the exact sequence of individual clips chosen by the AI.
2. **Individual Clip Previews**: 
   - *Backend*: `/jobs/{id}/clips/urls`
   - *Concept*: Users can click on individual blocks in the timeline to preview the trimmed segment of the video before the final render is glued together.
3. **Live Terminal Logs**: 
   - *Backend*: `GET /api/v1/jobs/{job_id}/logs`
   - *Concept*: Instead of a basic progress bar during the `RUNNING` state, show a hacker-style "Terminal" window that streams the backend Celery logs in real-time (e.g., `[INFO] Extracted 45 frames`, `[INFO] LLM reasoning completed`).

---

## 5. Summary of Data Types
- **Project**: `{ id, name, user_id, created_at }`
- **MediaAsset**: `{ id, project_id, filename, object_key, is_image, sequence_index, file_size_bytes, presigned_url }`
- **JobStatus**: `{ id, project_id, status (PENDING|RUNNING|STORY_PROPOSED|COMPLETED|FAILED), progress, error_message, story_summary, final_video_url }`
