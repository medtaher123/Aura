from datetime import datetime, timedelta
import re
import requests
from langchain_core.tools import tool
from requests.exceptions import RequestException, Timeout

STAC_API_URL = "https://earth-search.aws.element84.com/v1"
REQUEST_TIMEOUT = 10


@tool(return_direct=True)
def query_stac_catalog(params: str) -> dict:
    """
    Query the STAC EarthSearch catalog to retrieve satellite images for a bbox,
    a time window, and a collection.

    Params format:
    "lon_min,lat_min,lon_max,lat_max start_date end_date collection"
    Example:
    "10.1,36.7,10.3,36.9 2023-07-01 2023-07-10 sentinel-2-l2a"
    """
    try:
        match = re.match(
            r"([0-9\.\,\-]+)\s+(\d{4}-\d{2}-\d{2})\s+(\d{4}-\d{2}-\d{2})\s+([\w\-]+)",
            params.strip(),
        )
        if not match:
            return {"error": f"Invalid parameters format for STAC params: {params}"}

        bbox_str, start_date, end_date, collection = match.groups()
        bbox = [float(x) for x in bbox_str.split(",")]
        date_format = "%Y-%m-%d"

        start = datetime.strptime(start_date, date_format)
        end = datetime.strptime(end_date, date_format)

        all_images = []
        current = start

        while current <= end:
            date_str = current.strftime(date_format)

            body = {
                "collections": [collection],
                "bbox": bbox,
                "datetime": f"{date_str}T00:00:00Z/{date_str}T23:59:59Z",
                "limit": 3,
            }

            try:
                response = requests.post(
                    f"{STAC_API_URL}/search",
                    json=body,
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
            except Timeout:
                return {"error": "Timeout while calling STAC API."}
            except RequestException as exc:
                return {"error": f"STAC network error: {exc}"}

            try:
                items = response.json().get("features", [])
            except ValueError as exc:
                return {"error": f"Invalid STAC response: {exc}"}

            if items:
                item = items[0]
                image_data = {
                    "date": date_str,
                    "cloud_cover": item.get("properties", {}).get("eo:cloud_cover", "N/A"),
                    "thumbnail": item.get("assets", {}).get("thumbnail", {}).get("href", ""),
                }
                all_images.append(image_data)

            current += timedelta(days=1)

        if not all_images:
            return {
                "message": (
                    f"No images found for {collection} between {start_date} and {end_date} "
                    f"for bbox {bbox_str}."
                ),
                "collection": collection,
                "bbox": bbox_str,
                "start_date": start_date,
                "end_date": end_date,
                "images": [],
            }

        urls = [img["thumbnail"] for img in all_images if img.get("thumbnail")]
        details = "\n".join(
            [
                f"- {img['date']}: cloud_cover={img.get('cloud_cover', 'N/A')}% thumbnail={img.get('thumbnail', '')}"
                for img in all_images
            ]
        )

        return {
            "message": (
                f"Found {len(all_images)} images for {collection} between {start_date} and {end_date} "
                f"for bbox {bbox_str}.\n{details}\nThumbnails: {', '.join(urls)}"
            ),
            "collection": collection,
            "bbox": bbox_str,
            "start_date": start_date,
            "end_date": end_date,
            "images": all_images,
            "thumbnails": urls,
        }

    except Exception as exc:
        return {"error": f"Unexpected STAC error: {exc}"}