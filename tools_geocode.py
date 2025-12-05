#tools_geocode.py
import requests

def get_city_bbox(city_name):
    url = f'https://nominatim.openstreetmap.org/search?q={city_name}&format=json&limit=1'
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = response.json()
        if not data:
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
        else:
            return None, None, None, None, city_name
    except Exception:
        return None, None, None, None, city_name



