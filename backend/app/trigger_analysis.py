import asyncio
import httpx
import uuid
import time
import sys

BASE_URL = "http://localhost:8000/api/v1"
PROJECT_ID = "205159d3-1e80-41c7-9965-2e7027ef3578"

DIRECTIVES = """
To move this edit from "home video" to "professional highlight reel," we need to focus on structure, pacing, and visual storytelling.

Think of your video as a story with three acts: Arrival, Experience, and Reflection. Currently, your clips are scattered, which breaks the immersion.

Here is the professional workflow to restructure your video:

### 1. Reorganize the "Acts" (Logical Flow)

Stop jumping between locations. Group your clips so the viewer can follow your day naturally.

* **Act I: The Arrival (Setting the Scene):**
* Start with the **archway/garden** (00:00). These are your "establishing shots." They tell the viewer *where* we are.
* Transition to the **city/architecture** (00:04). This builds the scale of the environment.


* **Act II: The Experience (High Energy):**
* Transition to the **boat/water shots** (00:08, 00:23).
* Follow with the **pool action** (00:17, 00:33).
* *Tip:* Keep all "wet/active" footage in this block.


* **Act III: The Reflection (Slow Down):**
* End with the **temple/candles** (00:42). The light of the candles and the slow pace of that scene make for a perfect "emotional" closing.

### 2. Deep Dive: Fixing the "Fluidity" Issues

You mentioned you like Fades, Dissolves, and Zooms. Let's apply them with specific "editing logic":

* **The Cross-Dissolve (The "Bridge"):**
* **When to use:** Use this *only* when changing from one "Act" to the next.
* *Example:* Dissolve from the city architecture into the boat ride. It tells the viewer: "We are moving from the city to the water."

* **The Zoom-In (The "Emphasis"):**
* **When to use:** Use this *inside* the Acts, on the most exciting second of a clip.
* *Example:* In your pool clip, as someone hits the water, have the camera "Zoom In" slightly. It mimics a human's instinct to look closer at a splash.

* **The Fade (The "Bookends"):**
* **When to use:** Fade *from* black to open the video, and fade *to* black when you cut to the final shot of the temple candles. Do not use fades anywhere else, or the video will feel "sleepy."

### 3. Killing the Duplication

Repetition is the #1 way to lose a viewer's attention.

* **The "Rule of One":** If you have two clips of the same pool jump, pick the **one** that is clearest and has the best light. **Delete the other.**

### 4. Technical Pacing: "The Rhythm of the Cut"

If your video feels "jarring," it is usually because the clips are either too long or have no consistent rhythm.

* **The "Beat" Test:** If you add a song, try to place your cuts exactly when the drums or bass hit.
* **Static Clip Logic:** Your temple/candle shot is beautiful. Don't cut it quickly. Let it linger for 3–4 seconds. In contrast, your pool/action shots should be fast—maybe 1.5–2 seconds per clip. **Varying your clip length keeps the video dynamic.**

### Editor's Checklist for your next draft:

1. **Cut the Repeats:** Delete all duplicate pool/garden shots.
2. **Sequence the Acts:** Sort into Arrival → Action → Reflection.
3. **Apply Transitions:**
* Dissolve between Acts.
* Zoom into the action.
* Fade at the very start/end.
4. **Trim for Energy:** Ensure no clip lasts longer than 3 seconds unless it's a slow "cinematic" beauty shot.
"""

def main():
    # 1. Register/Login a test user
    email = f"runner_{uuid.uuid4().hex[:6]}@example.com"
    password = "securepassword123"
    print(f"Registering runner user {email}...")
    
    r = httpx.post(f"{BASE_URL}/auth/register", json={"email": email, "password": password})
    if r.status_code != 201:
        print(f"Registration failed: {r.status_code} - {r.text}")
        # Try logging in directly with a default if already registered, or exit
        print("Will try direct login...")
    
    print("Logging in to retrieve access token...")
    r = httpx.post(f"{BASE_URL}/auth/token", data={"username": email, "password": password})
    if r.status_code != 200:
        print(f"Login failed: {r.status_code} - {r.text}")
        sys.exit(1)
        
    token = r.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Trigger analysis job
    payload = {
        "vibe": "cinematic",
        "directives": DIRECTIVES
    }
    print(f"Submitting analysis job for project {PROJECT_ID}...")
    r = httpx.post(f"{BASE_URL}/projects/{PROJECT_ID}/analyze", json=payload, headers=headers, timeout=30.0)
    if r.status_code != 200:
        print(f"Failed to start job: {r.status_code} - {r.text}")
        sys.exit(1)
        
    job_info = r.json()
    job_id = job_info.get("id")
    print(f"Job successfully started! ID: {job_id}")
    
    # 3. Poll job status
    print("Polling job status (this may take a few minutes)...")
    while True:
        r = httpx.get(f"{BASE_URL}/jobs/{job_id}", headers=headers)
        if r.status_code != 200:
            print(f"Error checking status: {r.status_code} - {r.text}")
            time.sleep(5)
            continue
            
        status_data = r.json()
        status = status_data.get("status")
        progress = status_data.get("progress")
        error_msg = status_data.get("error_message")
        
        print(f"  [Status] Status: {status} | Progress: {progress}%")
        
        if status == "completed":
            print(f"\n✅ Job completed successfully!")
            print(f"Final video URL: {status_data.get('final_video_url')}")
            break
        elif status == "failed":
            print(f"\n❌ Job failed! Error: {error_msg}")
            sys.exit(1)
            
        time.sleep(5)

if __name__ == "__main__":
    main()
