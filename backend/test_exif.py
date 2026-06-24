from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

def get_exif_data(image_path):
    exif_data = {}
    try:
        image = Image.open(image_path)
        info = image._getexif()
        if info:
            for tag, value in info.items():
                decoded = TAGS.get(tag, tag)
                if decoded == "GPSInfo":
                    gps_data = {}
                    for t in value:
                        sub_decoded = GPSTAGS.get(t, t)
                        gps_data[sub_decoded] = value[t]
                    exif_data[decoded] = gps_data
                else:
                    exif_data[decoded] = value
    except Exception as e:
        pass
    return exif_data

def get_lat_lon(exif_data):
    if "GPSInfo" in exif_data:
        gps_info = exif_data["GPSInfo"]
        
        def convert_to_degrees(value):
            d, m, s = value
            return float(d) + (float(m) / 60.0) + (float(s) / 3600.0)
            
        lat = None
        lon = None
        if "GPSLatitude" in gps_info and "GPSLatitudeRef" in gps_info:
            lat = convert_to_degrees(gps_info["GPSLatitude"])
            if gps_info["GPSLatitudeRef"] != "N":
                lat = -lat
                
        if "GPSLongitude" in gps_info and "GPSLongitudeRef" in gps_info:
            lon = convert_to_degrees(gps_info["GPSLongitude"])
            if gps_info["GPSLongitudeRef"] != "E":
                lon = -lon
                
        return lat, lon
    return None, None

print(get_lat_lon({}))
