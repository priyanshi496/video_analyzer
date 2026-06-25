import subprocess
import json
from pathlib import Path
import logging
import cv2
import requests
import re
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

GEOCODE_CACHE = {}

def get_lat_lon_from_exif(image_path):
    try:
        image = Image.open(image_path)
        info = image._getexif()
        if not info: return None, None
        
        gps_info = None
        for tag, value in info.items():
            decoded = TAGS.get(tag, tag)
            if decoded == "GPSInfo":
                gps_info = {GPSTAGS.get(t, t): value[t] for t in value}
                break
                
        if not gps_info: return None, None
        
        def convert_to_degrees(value):
            d, m, s = value
            return float(d) + (float(m) / 60.0) + (float(s) / 3600.0)
            
        lat = lon = None
        if "GPSLatitude" in gps_info and "GPSLatitudeRef" in gps_info:
            lat = convert_to_degrees(gps_info["GPSLatitude"])
            if gps_info["GPSLatitudeRef"] != "N": lat = -lat
                
        if "GPSLongitude" in gps_info and "GPSLongitudeRef" in gps_info:
            lon = convert_to_degrees(gps_info["GPSLongitude"])
            if gps_info["GPSLongitudeRef"] != "E": lon = -lon
                
        return lat, lon
    except Exception:
        return None, None

def get_time_from_exif(image_path):
    try:
        image = Image.open(image_path)
        info = image._getexif()
        if not info: return None
        for tag, value in info.items():
            if TAGS.get(tag, tag) == "DateTimeOriginal":
                return value
    except Exception:
        pass
    return None

def reverse_geocode(lat, lon):
    if not lat or not lon: return None
    key = f"{round(lat, 3)},{round(lon, 3)}"
    if key in GEOCODE_CACHE: return GEOCODE_CACHE[key]
    
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
    headers = {"User-Agent": "VideoAnalyzerBot/1.0", "Accept-Language": "en"}
    try:
        r = requests.get(url, headers=headers, timeout=3)
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
            
            res = ", ".join(parts) if parts else data.get("display_name")
            GEOCODE_CACHE[key] = res
            return res
    except Exception as e:
        print(f"Geocode failed: {e}")
    return None
