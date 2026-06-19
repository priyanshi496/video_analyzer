import subprocess
import json

def probe_streams(file_path):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", file_path]
    out = subprocess.check_output(cmd, text=True)
    data = json.loads(out)
    streams = [s.get("codec_type") for s in data.get("streams", [])]
    return "video" in streams, "audio" in streams

print(probe_streams("test_script.py"))
