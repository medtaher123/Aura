#water_ingress.py
import os
from pathlib import Path
import requests
import rasterio
import numpy as np
import matplotlib.pyplot as plt
from langchain.tools import tool

from .contracts import make_tool_response
from rasterio.features import geometry_mask
from shapely.geometry import Point, shape

from src.services.bbox_service import get_city_candidates

# OpenTopography API key
OPENTOP_API_KEY = os.getenv("OPENTOPO_API_KEY", "811d1f7cbb4522dc7e623ec70a657ed1")
MAPS_DIR = Path(__file__).resolve().parents[1] / "maps"
MAPS_DIR.mkdir(parents=True, exist_ok=True)

# Geocoding (name -> lat/lon)
def geocode_city(city_name: str):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": city_name, "format": "json", "limit": 1, "polygon_geojson": 1}
    r = requests.get(url, params=params, headers={"User-Agent": "SurfaceIngressTool"})
    data = r.json()
    if not data:
        raise ValueError(f"City not found: {city_name}")
    
    lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
    bbox = [float(x) for x in data[0]["boundingbox"]]
    polygon = data[0].get("geojson")  # le polygone réel de la ville
    return lat, lon, bbox, polygon



# Reverse geocoding (lat/lon -> city/country)
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

def download_dem_opentopo(lat: float, lon: float, bbox=None, polygon=None, dem_file="dem_city.tif"):
    # 1️⃣ Calculer la bounding box pour le téléchargement
    if bbox:
        min_lat, max_lat = bbox[0], bbox[1]
        min_lon, max_lon = bbox[2], bbox[3]
    else:
        buffer_deg = 0.1
        min_lat, max_lat = lat - buffer_deg, lat + buffer_deg
        min_lon, max_lon = lon - buffer_deg, lon + buffer_deg

    # 2️⃣ Télécharger le DEM
    url = "https://portal.opentopography.org/API/globaldem"
    params = {
        "demtype": "SRTMGL3",
        "west": min_lon, "south": min_lat, "east": max_lon, "north": max_lat,
        "outputFormat": "GTiff",
        "API_Key": OPENTOP_API_KEY
    }
    r = requests.get(url, params=params, stream=True)
    if r.status_code != 200:
        raise ValueError(f"Unable to download DEM. Status code: {r.status_code}")
    with open(dem_file, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    print('polygon:', polygon)
    # 3️⃣ Appliquer le masque polygone si fourni
    if polygon:
        with rasterio.open(dem_file, "r+") as src:
            dem = src.read(1).astype(np.float32)
            if src.nodata is not None:
                dem[dem == src.nodata] = np.nan

            mask = geometry_mask([polygon], transform=src.transform, invert=True, out_shape=dem.shape)
            dem_masked = np.where(mask, dem, np.nan)

            # Remplacer le DEM par le DEM masqué
            src.write(dem_masked, 1)

    return dem_file


#D8 Flow Direction & Accumulation
def d8_flow_direction_and_accum(dem: np.ndarray):
    neighbors = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
    h, w = dem.shape
    dir_idx = np.full((h, w), -1, dtype=int)
    for y in range(1, h-1):
        for x in range(1, w-1):
            z0 = dem[y, x]
            zmin = z0
            kmin = -1
            for k, (dy, dx) in enumerate(neighbors):
                z = dem[y + dy, x + dx]
                if z < zmin:
                    zmin = z
                    kmin = k
            dir_idx[y, x] = kmin
    acc = np.ones_like(dem, dtype=np.float32)
    indices = np.argsort(dem, axis=None)
    ys, xs = np.unravel_index(indices, dem.shape)
    for y, x in zip(ys, xs):
        k = dir_idx[y, x]
        if k >= 0:
            dy, dx = neighbors[k]
            yy, xx = y + dy, x + dx
            if 0 <= yy < h and 0 <= xx < w:
                acc[yy, xx] += acc[y, x]
    return acc, dir_idx

# Mitigation actions
def mitigation_rules(dem, slope, acc, risk_mask):
    actions = []
    risk_percent = 100.0 * np.sum(risk_mask) / risk_mask.size
    mean_slope_rel = np.nanmean(slope)
    high_acc_mask = acc >= np.percentile(acc, 95)
    low_mask = dem <= np.percentile(dem, 5)

    if risk_percent >= 10:
        actions += [{"description": "Create small diversion channels or berms to divert upstream water.",
                     "resource": "https://www.ecologie.gouv.fr/sites/default/files/documents/Gestion_durable_des_eaux_pluviales_le_plan_daction.pdf"},
                    {"description": "Install flood boards or sandbag barriers at openings.",
                     "resource": "https://www.georisques.gouv.fr/reduire-la-vulnerabilite-de-ma-maison-aux-inondations"}]

    if mean_slope_rel < 0.02:
        actions += [{"description": "Re-profile the terrain to obtain a slope > 2%.",
                     "resource": "https://www.cerema.fr/fr/actualites/gestion-durable-eaux-pluviales-etude-benefices-apportes"},
                    {"description": "Add a linear gutter in front of thresholds connected to the stormwater network.",
                     "resource": "https://www.sdea.fr/images/SDEA/GEPU/Guide_pratique_particulier_WEB.pdf"}]

    if np.any(high_acc_mask & risk_mask):
        actions += [{"description": "Install a french drain along flow paths.",
                     "resource": "https://www.sdea.fr/images/SDEA/GEPU/Guide_pratique_particulier_WEB.pdf"},
                {"description": "Maintain gutters/inlets and check outlets.",
                     "resource": "https://www.cerema.fr/fr/actualites/gestion-durable-eaux-pluviales-etude-benefices-apportes"}]

    if np.any(low_mask & risk_mask):
        actions += [{"description": "Create a controlled low point with a pump.",
                     "resource": "https://www.biodiversite-centrevaldeloire.fr/comprendre/les-solutions-d-adaptation-fondees-sur-la-nature/des-solutions-pour-reduire-les-risques-inondations"},
                {"description": "Slightly raise depressions near building facades.",
                     "resource": "https://www.adaptation-changement-climatique.gouv.fr/dossiers-thematiques/impacts/inondation"}]

    if 3 <= risk_percent < 10 and mean_slope_rel >= 0.02:
        actions += [{"description": "Plant vegetated strips (bioswales).",
                     "resource": "https://www.ecologie.gouv.fr/sites/default/files/documents/Gestion_durable_des_eaux_pluviales_le_plan_daction.pdf"},
                {"description": "Direct downspouts away from foundations.",
                     "resource": "https://www.georisques.gouv.fr/reduire-la-vulnerabilite-de-ma-maison-aux-inondations"}]

    actions += [{"description": "Regularly clean grates, gutters and inspection chambers.",
                 "resource": "https://www.environnement.gouv.qc.ca/eau/pluviales/guide-gestion-eaux-pluviales.pdf"},
                {"description": "Check the sealing of thresholds and joints.",
                 "resource": "https://www.ecologie.gouv.fr/politiques-publiques/prevention-inondations"}]

    # Supprimer doublons
    seen = set()
    unique_actions = []
    for a in actions:
        if a["description"] not in seen:
            unique_actions.append(a)
            seen.add(a["description"])
    return unique_actions

#Estimation principale
def estimate_surface_water_ingress(location_input):
    if isinstance(location_input, str):
        lat, lon, bbox, polygon = geocode_city(location_input)
        location_info = reverse_geocode(lat, lon)
    elif isinstance(location_input, (tuple, list)) and len(location_input) == 2:
        lat, lon = location_input
        bbox = None
        polygon = None
        # call reverse geocode for coordinates
        location_info = reverse_geocode(lat, lon)
    else:
        raise ValueError("Invalid input. Use a city name or a (lat, lon) tuple.")


    dem_file = download_dem_opentopo(lat, lon, bbox=bbox)

    try:
        with rasterio.open(dem_file) as src:
            dem = src.read(1).astype(np.float32)
            if src.nodata is not None:
                dem[dem == src.nodata] = np.nan
            dem[np.isnan(dem)] = np.nanmedian(dem)
            transform = src.transform

        gy, gx = np.gradient(dem)
        slope = np.sqrt(gx**2 + gy**2)
        acc, _ = d8_flow_direction_and_accum(dem)

        low_mask = dem <= np.nanpercentile(dem, 0.05)
        flat_mask = slope <= 0.0005
        highacc = acc >= np.percentile(acc, 99.7)
        risk_mask = (low_mask & flat_mask) | highacc

        stats = {
            "DEM_shape": dem.shape,
            "Elevation_min": float(np.nanmin(dem)),
            "Elevation_max": float(np.nanmax(dem)),
            "Elevation_mean": float(np.nanmean(dem)),
            "Slope_mean": float(np.nanmean(slope)),
            "Risk_zone_percent": float(100.0 * np.sum(risk_mask) / risk_mask.size)
        }

        actions = mitigation_rules(dem, slope, acc, risk_mask)

        # Matplotlib maps
        plt.imsave(MAPS_DIR / "map_elevation.png", dem, cmap="terrain")
        plt.imsave(MAPS_DIR / "map_slope.png", slope, cmap="inferno")
        plt.imsave(MAPS_DIR / "map_flowacc.png", acc, cmap="Blues")
        plt.imsave(MAPS_DIR / "Map_risk.png", risk_mask.astype(float), cmap="Reds")

        # Build risk points for Pydeck (sampled to keep payload reasonable)
        risk_coords = np.argwhere(risk_mask)

        polygon_shape = None
        if polygon:
            try:
                polygon_shape = shape(polygon)
            except Exception:
                polygon_shape = None

        risk_points = []
        for y, x in risk_coords:
            try:
                rlon, rlat = rasterio.transform.xy(transform, int(y), int(x))
                if polygon_shape is not None and not polygon_shape.contains(Point(rlon, rlat)):
                    continue
                risk_points.append({"lat": float(rlat), "lon": float(rlon)})
            except Exception:
                continue

        max_points = 2500
        if len(risk_points) > max_points:
            rng = np.random.default_rng(0)
            idx = rng.choice(len(risk_points), size=max_points, replace=False)
            risk_points = [risk_points[i] for i in idx]

        return {
            "Ingress_paths_estimate": "Water follows the D8 flow paths towards low points.",
            "Mitigation_actions": actions,
            **stats,
            "Maps": {
                "Risk_points": risk_points
            },
            "Explanation": (
                "How to read the maps:\n"
                "Risk map: red areas indicate likely accumulation."
            ),
            "Location": location_info,
            "Coordinates": {"lat": float(lat), "lon": float(lon)},
        }
    finally:
        if os.path.exists(dem_file):
            os.remove(dem_file)


@tool(return_direct=True)
def estimate_surface_water_ingress_tool(location_input: str) -> dict:
    """
     Full analysis of surface water ingress risk for a given area.

     Input:
     - A city name (str), e.g., "Paris", or
     - A coordinate tuple (lat, lon), e.g., (48.8566, 2.3522).

    The final output is: Final Answer: <message>

    Process:
     - Geocoding (city name -> lat/lon) if needed.
     - Download DEM from OpenTopography.
     - Compute slope and D8 flow accumulation.
     - Identify risk areas (low elevation, low slope, high accumulation).
        - Generate Matplotlib maps and a Pydeck-ready set of risk points.
     - Apply mitigation rules to propose actions.
    """
    try:
        if isinstance(location_input, str) and location_input.strip():
            candidates = get_city_candidates(location_input.strip())
            if len(candidates) > 1:
                return make_tool_response(
                    tool_name="estimate_surface_water_ingress_tool",
                    message=(
                        f"I found multiple matches for '{location_input}'. "
                        "Please confirm the correct location."
                    ),
                    city=location_input,
                    data={
                        "needs_location_confirmation": True,
                        "location_query": location_input,
                        "candidates": candidates,
                        "resume_patch": {"field": "location_input"},
                    },
                    error=True,
                )
        result = estimate_surface_water_ingress(location_input)

        ingress = result.get("Ingress_paths_estimate", "Not available")
        mitigation = result.get("Mitigation_actions", [])
        stats = result.get("Statistics", {})
        maps = result.get("Maps", {})
        explanation = result.get("Explanation", "Not available")

        # -------- TEXT ASSEMBLY --------
        message_parts = []

        message_parts.append(f"📍 *Surface Water Ingress Risk Analysis for*: **{location_input}**\n")

        message_parts.append("### 🌊 Estimated Water Flow Paths")
        message_parts.append(ingress)

        if mitigation:
            message_parts.append("\n### 🛠 Recommended Mitigation Actions")
            for action in mitigation:
                message_parts.append(f"- {action}")

        if stats:
            message_parts.append("\n### 📊 Terrain & Risk Statistics")
            message_parts.append(f"- DEM Shape: {stats.get('DEM_shape')}")
            message_parts.append(f"- Elevation Min/Max/Mean: {stats.get('Elevation_min')} / "
                                 f"{stats.get('Elevation_max')} / {stats.get('Elevation_mean')}")
            message_parts.append(f"- Mean Slope: {stats.get('Slope_mean')}")
            message_parts.append(f"- Risk Zone Coverage: {stats.get('Risk_zone_percent')}%")

        if maps:
            message_parts.append("\n### 🗺 Generated Maps")
            for key, path in maps.items():
                if key == "Risk_points" and isinstance(path, list):
                    message_parts.append(f"- **{key}**: {len(path)} point(s)")
                else:
                    message_parts.append(f"- **{key}**: {path}")

        if explanation:
            message_parts.append("\n### ℹ️ How to Interpret the Maps")
            message_parts.append(explanation)

        # Join message
        message = "\n".join(message_parts)

        artifacts = {"maps": [], "thumbnails": [], "urls": []}
        if isinstance(maps, dict):
            risk_points = maps.get("Risk_points")
            coords = result.get("Coordinates")
            if isinstance(risk_points, list) and isinstance(coords, dict):
                artifacts["maps"].append(
                    {
                        "title": "Surface water ingress risk",
                        "points": risk_points,
                        "view_state": {
                            "latitude": float(coords.get("lat", 0.0) or 0.0),
                            "longitude": float(coords.get("lon", 0.0) or 0.0),
                            "zoom": 14,
                        },
                        "tooltip": {"text": ""},
                        "fill_color": [255, 0, 0, 120],
                        "radius": 5,
                        "radius_units": "pixels",
                        "radius_min_pixels": 2,
                        "radius_max_pixels": 7,
                    }
                )

        coords = None
        try:
            c = result.get("Coordinates")
            if isinstance(c, dict) and c.get("lat") is not None and c.get("lon") is not None:
                coords = {"lat": float(c["lat"]), "lon": float(c["lon"])}
        except Exception:
            coords = None

        location_info = result.get("Location") or {}

        country = None
        city = None
        if isinstance(location_info, dict):
            country = location_info.get("country")
            city = location_info.get("city")

        return make_tool_response(
            tool_name="estimate_surface_water_ingress_tool",
            message=message,
            artifacts=artifacts,
            country=country,
            city=city,
            coordinates=coords,
            data={"result": result},
            error=False,
        )

    except Exception as e:
        error_message = f"An error occurred while processing the request: {str(e)}"
        return make_tool_response(
            tool_name="estimate_surface_water_ingress_tool",
            message=error_message,
            error=True,
        )