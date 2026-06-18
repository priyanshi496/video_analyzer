import base64
import requests
import json
import os
import subprocess

API_KEY = "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"

# Using the file in the workspace directory to avoid macOS permission issues
AUDIO_FILE = "//Users/tsc/Desktop/video_analyzer/Hamari Adhuri Kahani(KoshalWorld.Com).mp3"
OUTPUT_FILE = "/Users/tsc/Desktop/video_analyzer/song_analysis_hamari_adhuri_kahani.txt"

cropped_audio_file = AUDIO_FILE.replace(".mp3", "_cropped.mp3")
print(f"Cropping audio file to max 3 minutes using ffmpeg...")
try:
    # Run ffmpeg to cut the first 3 minutes (180 seconds)
    subprocess.run([
        "ffmpeg", "-y", "-i", AUDIO_FILE, "-t", "180", "-c", "copy", cropped_audio_file
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Successfully cropped audio.")
except Exception as e:
    print(f"Error running ffmpeg. Make sure ffmpeg is installed. {e}")
    exit(1)

print(f"Reading cropped audio file from: {cropped_audio_file}")
try:
    with open(cropped_audio_file, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")
except FileNotFoundError:
    print(f"Error: The audio file was not found. Please make sure the file exists at {cropped_audio_file}")
    exit(1)
except PermissionError:
    print(f"Error: Permission denied. The terminal does not have access to read {cropped_audio_file}")
    exit(1)
finally:
    if os.path.exists(cropped_audio_file):
        os.remove(cropped_audio_file)

payload = {
    "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": """
                    Listen to the provided audio clip and provide the following information in a structured format:
                    
                    LYRICS:
                    [Write the full lyrics you hear. CRITICAL: Do not get stuck repeating the same phrase infinitely. If a phrase repeats, just write '(repeats X times)'.]
                    
                    HOOK:
                    [Identify the main hook/chorus of the song]
                    
                    VIBE:
                    [Describe the vibe, mood, and feel of the song in a short paragraph]
                    """
                },
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": audio_b64,
                        "format": "mp3"
                    }
                }
            ]
        }
    ],
    "temperature": 0.5
}

print("Sending request to NVIDIA API... This may take a few minutes.")
response = requests.post(
    "https://integrate.api.nvidia.com/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    },
    json=payload,
    timeout=600
)

print("Status Code:", response.status_code)

if response.status_code == 200:
    try:
        data = response.json()
        message = data.get("choices", [{}])[0].get("message", {})
        
        # Nemotron reasoning models often output the text in 'reasoning_content'
        content = message.get("content")
        reasoning_content = message.get("reasoning_content")
        
        final_output = content if content else reasoning_content
        
        if final_output:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                f.write("=== SONG ANALYSIS ===\n\n")
                f.write(final_output)
            print(f"✅ Analysis complete! Output successfully saved to: {OUTPUT_FILE}")
        else:
            print("Response did not contain valid text content.")
            print(json.dumps(data, indent=2))
            
    except Exception as e:
        print(f"Error parsing response: {e}")
        print(response.text)
else:
    print("API Request Failed:")
    print(response.text)