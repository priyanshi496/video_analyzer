import requests
import re

def parse_iso6709(loc_str):
    # Matches +27.5916+086.5640/ or +27.5916-086.5640/
    match = re.match(r"([+-]\d+\.\d+)([+-]\d+\.\d+)", loc_str)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None, None

def reverse_geocode(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
    headers = {"User-Agent": "VideoAnalyzerBot/1.0"}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        data = r.json()
        address = data.get("address", {})
        parts = []
        if "amenity" in address: parts.append(address["amenity"])
        elif "historic" in address: parts.append(address["historic"])
        elif "tourism" in address: parts.append(address["tourism"])
        
        if "city" in address: parts.append(address["city"])
        elif "town" in address: parts.append(address["town"])
        elif "village" in address: parts.append(address["village"])
        
        if "state" in address: parts.append(address["state"])
        if "country" in address: parts.append(address["country"])
        return ", ".join(parts) if parts else data.get("display_name")
    return None

print(reverse_geocode(22.164, 71.782)) # Approx coords for Sarangpur Hanuman, Gujarat
