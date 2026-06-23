import re

with open("app/services/pipeline_service.py", "r") as f:
    code = f.read()

# Fix 1: call_openrouter_multiimage unexpected keyword api_key
code = code.replace("call_openrouter_multiimage(prompt, image_paths, api_key=api_key)", "call_openrouter_multiimage(prompt, image_paths)")

# Fix 2: 'BeatMap' object has no attribute 'beat_times'
# I'll replace beat_map.beat_times with [b['time'] for b in beat_map.beat_grid]
# Actually, I can just find occurrences of beat_map.beat_times and replace them.
code = code.replace("beat_map.beat_times", "[b['time'] for b in beat_map.beat_grid]")

# Fix 3: 'NoneType' object has no attribute 'lower' in deduplicate_by_source_video
code = code.replace("desc_clip = (clip.get(\"what_happens\", \"\") or clip.get(\"reason\", \"\")).lower()", "desc_clip = (clip.get(\"what_happens\") or clip.get(\"reason\") or \"\").lower()")

with open("app/services/pipeline_service.py", "w") as f:
    f.write(code)

print("Fixes applied.")
