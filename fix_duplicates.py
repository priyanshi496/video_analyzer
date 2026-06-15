import json

def fix_file(path):
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        
        seen = set()
        new_data = []
        for item in data:
            if item.get("is_used") is False:
                new_data.append(item)
                continue
            
            vp = item.get("video_path")
            if vp not in seen:
                seen.add(vp)
                new_data.append(item)
                
        with open(path, 'w') as f:
            json.dump(new_data, f, indent=2)
        print(f"Fixed {path}: {len(data)} -> {len(new_data)} items")
    except Exception as e:
        print(e)

fix_file("best_segments.json")
fix_file("active_segments.json")
