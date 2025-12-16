#tools_geocode.py
import time
import requests

def get_city_bbox(city_name):
    url = f'https://nominatim.openstreetmap.org/search?q={city_name}&format=json&limit=1'
    for attempt in range(5):
        try:
            print(f"Debug: Attempting to get bounding box for city: {city_name}, attempt {attempt + 1}")
            response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            data = response.json()
            print(f"Debug: Nominatim response data: {data}")
            if not data:
                if attempt < 4:
                    time.sleep(1)
                    continue
                return None, None, None, None, city_name
            
            bbox = data[0].get('boundingbox', None)
            if bbox:
                lat_min = float(bbox[0])
                lat_max = float(bbox[1])
                lon_min = float(bbox[2])
                lon_max = float(bbox[3])
                display_name = data[0].get("display_name", city_name)
                name = display_name.split(",")[0]
                return lon_min, lat_min, lon_max, lat_max, name
        except Exception:
            if attempt < 4:
                time.sleep(1)
                continue
            print("Error: Failed to get bounding box from Nominatim after multiple attempts.")
            return None, None, None, None, city_name
