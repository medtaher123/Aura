from datetime import datetime, timedelta
import re
import requests
from langchain_core.tools import tool
from requests.exceptions import RequestException, Timeout
from langchain_ollama import OllamaLLM
from src.services.bbox_service import get_city_bbox
import json
from ast import literal_eval

from .contracts import make_tool_response


STAC_API_URL = "https://earth-search.aws.element84.com/v1"
REQUEST_TIMEOUT = 10


def parse_llm_json(text: str) -> dict | None:
    """Parse LLM output into a dict; returns None on failure."""
    if isinstance(text, dict):
        return text
    # Remove code fences/backticks and trim
    cleaned = re.sub(r"^```[a-zA-Z0-9]*|```$", "", text.strip())
    # Normalize null/true/false variants
    cleaned = cleaned.replace("Null", "null").replace("NULL", "null")
    cleaned = cleaned.replace("True", "true").replace("False", "false")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            # Last resort for slightly invalid JSON
            return literal_eval(cleaned)
        except Exception:
            return None
        
def extract_bbox_and_dates(user_input: str) -> dict:
    try:
        # Ensure input is a string
        if not user_input:
            return {"error": "❌ Empty input string."}

        collection_map = {
            "sentinel-1": "sentinel-1-grd",
            "sentinel 1": "sentinel-1-grd",
            "sentinel-2": "sentinel-2-l2a",
            "sentinel 2": "sentinel-2-l2a",
            "modis": "firms-modis-c6",
            "viirs": "firms-viirs-nrt",
        }
  
        # --- LLM call to extract date and city ---
        system_prompt = """
        You are an assistant specialized in extracting structured information from user requests.
        Extract the start date, end date, location (city, region, or country), and collection from the user's text.
        if no dates are specified, return null for both start_date and end_date.
        if only one date is given, use it for both start_date and end_date.
        Return ONLY a JSON object in this exact format:

        {
        "start_date": "YYYY-MM-DD" or null,
        "end_date": "YYYY-MM-DD" or null,
        "location": "city/region/country name" or null,
        "collection": "collection name" or null
        }

        Do NOT include any explanations, instructions, or extra text. 
        Always respond with valid JSON.
        """

        few_shot_examples = """
        Example 1:
        User input: "Show me satellite viirs images of Paris in 2024"
        Response:
        {
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "location": "Paris",
        "collection": "viirs"
        }

        Example 2:
        User input: "I need images from Tunisia between 2023-12-01 and 2023-12-10"
        Response:
        {
        "start_date": "2023-12-01",
        "end_date": "2023-12-10",
        "location": "Tunisia",
        "collection": Null
        }

        Example 3:
        User input: "Get modis satellite imagery of Nice"
        Response:
        {
        "start_date": null,
        "end_date": null,
        "location": "Nice",
        "collection": "modis"
        }
        
        Example 4:
        User input: "I was in italy last summer, show me satellite sentinel-2 images there"
        Response:
        {
        "start_date": "2024-06-01",
        "end_date": 2024-08-31",
        "location": "Italy",
        "collection": "sentinel-2"
        }
        
        Example 5:
        User input: "there was a flood in luxembourg, show me sentinel 1 satellite images there on july 15 2023"
        Response:
        {
        "start_date": "2023-07-15",
        "end_date": "2023-07-15",
        "location": "Luxembourg",
        "collection": "sentinel-1"
        }
        """

        llm = OllamaLLM(
            model="mistral",
            temperature=0.3,
            system_prompt=system_prompt
        )

        prompt = f"Extract start date, end date, and location from the following text as JSON. {few_shot_examples}\n User input: \"{user_input}\""
        extracted = llm.invoke(prompt)
        print(f"Debug: LLM extracted: {extracted}")
        extracted = parse_llm_json(extracted)
        if not extracted:
            print("Debug: failed to parse LLM output into JSON")
            return {"error": "❌ Unable to parse LLM output."}
        else:
            print(f"Debug: parsed JSON: {extracted}")
        start_date = extracted.get("start_date")
        end_date = extracted.get("end_date")
        if start_date and not end_date:
            end_date = start_date
        if not start_date:
            start_date = datetime.now().strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        print(f"Debug: final start_date={start_date}, end_date={end_date}")    
        city_name = extracted.get("location")
        user_collection = extracted.get("collection") or ""
        collection = "sentinel-2-l2a"  # default
        for key, val in collection_map.items():
            if key in user_collection.lower():
                collection = val
                break
                
        if not city_name:
            print("Debug: No location found in input")
            return {"error": "❌ Unable to determine location."}

        # --- Use existing get_city_bbox for bounding box ---
        bbox_result = get_city_bbox(city_name)
        if not bbox_result:
            print(f"Debug: Invalid bbox_result: {bbox_result}")
            return {"error": f"❌ Location '{city_name}' not found or bbox unavailable."}

        bbox, lat, lon, city_name_final = bbox_result
        if not bbox:
            print(f"Debug: No bbox returned for city: {city_name}")
            return {"error": f"❌ Location '{city_name}' not found or bbox unavailable."}

        min_lat = float(bbox[0])
        max_lat = float(bbox[1])
        min_lon = float(bbox[2])
        max_lon = float(bbox[3])
        bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"

        return {
            "bbox": bbox,
            "start_date": start_date,
            "end_date": end_date,
            "collection": collection,
            "city": city_name_final,
        }

    except Exception as e:
        return {"error": f"❌ Error in extract_bbox_and_dates: {str(e)}"}
    
    
@tool(return_direct=True)
def query_stac_catalog(query_text: str) -> dict:
    """
    Query the STAC EarthSearch catalog to retrieve satellite images for a bbox, or a city, optionally a time window and a collection.
    
    Example user inputs:
    "satellite images in dresden from 2023-06-01 to 2023-06-05 sentinel-2" or "satellite images for Tunis" or "satellite images 10.0,36.0,11.0,37.0 2023-05-01 2023-05-03 sentinel-1"

    """
    try:
        data = extract_bbox_and_dates(query_text)
        print(f"Debug: extract_bbox_and_dates returned: {data}")
        if not data or data.get("error"):
            return make_tool_response(
                tool_name="query_stac_catalog",
                message=str(data.get("error", "Failed to extract search parameters.")),
                city=data.get("city") if isinstance(data, dict) else None,
                start_date=data.get("start_date") if isinstance(data, dict) else None,
                end_date=data.get("end_date") if isinstance(data, dict) else None,
                data={"raw": data} if isinstance(data, dict) else None,
                error=True,
            )
        bbox_str, start_date, end_date, collection, city_name= data.get("bbox"), data.get("start_date"), data.get("end_date"), data.get("collection"), data.get("city")
        print(f"Debug: extracted bbox={bbox_str}, start_date={start_date}, end_date={end_date}, collection={collection}, city_name={city_name}")
        if not bbox_str or not start_date or not end_date or not collection:
            return make_tool_response(
                tool_name="query_stac_catalog",
                message="Missing required search parameters (bbox/dates/collection).",
                city=city_name,
                start_date=start_date,
                end_date=end_date,
                data={"bbox": bbox_str, "collection": collection},
                error=True,
            )
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
                return make_tool_response(
                    tool_name="query_stac_catalog",
                    message="Timeout while calling STAC API.",
                    city=city_name,
                    start_date=start_date,
                    end_date=end_date,
                    data={"collection": collection, "bbox": bbox_str},
                    error=True,
                )
            except RequestException as exc:
                return make_tool_response(
                    tool_name="query_stac_catalog",
                    message=f"STAC network error: {exc}",
                    city=city_name,
                    start_date=start_date,
                    end_date=end_date,
                    data={"collection": collection, "bbox": bbox_str},
                    error=True,
                )

            try:
                items = response.json().get("features", [])
            except ValueError as exc:
                return make_tool_response(
                    tool_name="query_stac_catalog",
                    message=f"Invalid STAC response: {exc}",
                    city=city_name,
                    start_date=start_date,
                    end_date=end_date,
                    data={"collection": collection, "bbox": bbox_str},
                    error=True,
                )

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
            return make_tool_response(
                tool_name="query_stac_catalog",
                message=(
                    f"No images found for {collection} between {start_date} and {end_date} "
                    f"for bbox {bbox_str}."
                ),
                start_date=start_date,
                end_date=end_date,
                city=city_name,
                data={
                    "collection": collection,
                    "bbox": bbox_str,
                    "images": [],
                },
                error=False,
            )

        urls = [img["thumbnail"] for img in all_images if img.get("thumbnail")]
        details = "\n".join(
            [
                f"- {img['date']}: cloud_cover={img.get('cloud_cover', 'N/A')}% thumbnail={img.get('thumbnail', '')}"
                for img in all_images
            ]
        )

        return make_tool_response(
            tool_name="query_stac_catalog",
            message=(
                f"Found {len(all_images)} images for {collection} between {start_date} and {end_date} "
                f"for bbox {bbox_str}.\n{details}"
            ),
            artifacts={"maps": [], "thumbnails": urls, "urls": urls},
            start_date=start_date,
            end_date=end_date,
            city=city_name,
            data={
                "collection": collection,
                "bbox": bbox_str,
                "images": all_images,
            },
            error=False,
        )

    except Exception as exc:
        return make_tool_response(
            tool_name="query_stac_catalog",
            message=f"Unexpected STAC error: {exc}",
            error=True,
        )