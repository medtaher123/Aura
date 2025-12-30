#bbox_service.py
import time
import requests

    
def get_city_bbox(city_name):
    url = "https://nominatim.openstreetmap.org/search"
    geo_params = {"q": city_name, "format": "json", "limit": 3}
    for attempt in range(5):
        try:
            print(f"Debug: Attempting to get bounding box for city: {city_name}, attempt {attempt + 1}")
            response = requests.get(url, params=geo_params, headers={"User-Agent": "geocode-tool"})
            data = response.json()
            print(f"Debug: Nominatim response data: {data}")
            if not data:
                if attempt < 4:
                    time.sleep(1)
                    continue
                return None, None, None, city_name
            
            bbox = data[0].get('boundingbox', None)
            lat=data[0].get('lat', None)
            lon=data[0].get('lon', None)
            if bbox and lat and lon:
                display_name = data[0].get("display_name", city_name)
                name = display_name.split(",")[0]
                return bbox, lat, lon, name
        except Exception:
            if attempt < 4:
                time.sleep(1)
                continue
            print("Error: Failed to get bounding box from Nominatim after multiple attempts.")
            return None, None, None, city_name

def reverse_geocode(lat: float, lon: float):
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {"lat": lat, "lon": lon, "format": "json", "zoom": 10, "addressdetails": 1}
    r = requests.get(url, params=params, headers={"User-Agent": "SurfaceIngressTool"})
    data = r.json()
    address = data.get("address", {})
    city = address.get("city") or address.get("town") or address.get("village") or address.get("hamlet")
    country = address.get("country")
    country_code = address.get("country_code")
    return {"city": city, "country": country, "country_iso": country_code.upper() if country_code else None}