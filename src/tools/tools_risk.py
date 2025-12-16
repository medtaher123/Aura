from datetime import date, datetime, timedelta
import re
from dateparser.search import search_dates
from geopy.geocoders import Nominatim
from langchain.tools import tool
from langchain_ollama import OllamaLLM

# Local package imports (relative to src/tools)
from .tools_stac import query_stac_catalog
from .tools_geocode import get_city_bbox
from .fire_detection import detect_fire_tool
from .flood_detection import query_disaster_events_tool
from .water_ingress import estimate_surface_water_ingress_tool
from .geographic_info import geo_info_tool
from .itinerary import get_route_info
from .weather import weather_tool
from .general_chat import general_question_tool


geolocator = Nominatim(user_agent="my_app")

month_map = {
    "janvier": "01", "février": "02", "mars": "03", "avril": "04",
    "mai": "05", "juin": "06", "juillet": "07", "août": "08",
    "septembre": "09", "octobre": "10", "novembre": "11", "décembre": "12"
}


def extract_dates_from_text(text: str):
    """
    Extract a time window [start_date, end_date] from a free-form text string using
    `dateparser.search.search_dates` and safe token-based heuristics. 

    Behavior:
    - Prefer full-text `search_dates` result.
    - If multiple date matches -> min/max date returned.
    - If single match -> interpret as:
      - 4-digit year only -> full year range
      - month name + year (no day) -> full month range
      - otherwise: single day
    - If `search_dates` on full text returns None, try a sliding-window token scan
      and some normalizations to find date expressions.
    - For hyphenated ISO tokens (YYYY-MM-DD) we perform a safe string pattern check
      and parse them directly with `datetime.strptime` to ensure
      correct Y-M-D interpretation.
    """
    text_original = (text or "").strip()
    if not text_original:
        return None, None

    # Try parsing full text with search_dates first
    try:
        parsed = search_dates(text_original, settings={"DATE_ORDER": "DMY"})
    except Exception:
        parsed = None

    def tuples_from_parsed(parsed_list):
        return [(m[0].strip(), m[1]) for m in (parsed_list or []) if m and isinstance(m[1], datetime)]

    tuples = tuples_from_parsed(parsed)
    # Tokenize early for ISO detection and numeric-year fallback
    import re as _re
    raw_tokens = [t for t in _re.split(r"[\s,;]+", text_original) if t]
    from datetime import datetime as _dt
    def try_parse_iso(token: str):
        if len(token) == 10 and token[4] == '-' and token[7] == '-' and token[:4].isdigit():
            try:
                _d = _dt.strptime(token, "%Y-%m-%d").date()
                return _d
            except Exception:
                return None
        return None
    iso_dates = [try_parse_iso(t) for t in raw_tokens if try_parse_iso(t) is not None]
    if len(iso_dates) >= 2:
        iso_dates_sorted = sorted(iso_dates)
        return iso_dates_sorted[0].strftime("%Y-%m-%d"), iso_dates_sorted[-1].strftime("%Y-%m-%d")
    if len(iso_dates) == 1:
        return iso_dates[0].strftime("%Y-%m-%d"), iso_dates[0].strftime("%Y-%m-%d")
    if tuples:
        if len(tuples) >= 2:
            # If the matched texts contain explicit 4-digit year tokens, prefer
            # interpreting those as full-year ranges.
            texts = [t[0].strip() for t in tuples]
            year_texts = [tx for tx in texts if tx.isdigit() and len(tx) == 4]
            if len(year_texts) >= 2:
                y1, y2 = sorted(int(tx) for tx in year_texts)
                return f"{y1:04d}-01-01", f"{y2:04d}-12-31"
            dates = sorted([t[1] for t in tuples])
            return dates[0].strftime("%Y-%m-%d"), dates[-1].strftime("%Y-%m-%d")
        # single match: examine
        match_text, dt = tuples[0]
        mt = match_text.strip()
        # Year-only
        if mt.isdigit() and len(mt) == 4:
            y = int(mt)
            return f"{y:04d}-01-01", f"{y:04d}-12-31"
        # If match_text doesn't contain explicit day digits, treat as month-only
        tokens = [t.strip().lower() for t in mt.replace(',', ' ').split() if t.strip()]
        has_day_token = False
        for token in tokens:
            if token.isdigit():
                val = int(token) if token.isdigit() else None
                if val and 1 <= val <= 31:
                    has_day_token = True
                    break
            if token.endswith('er') and token[:-2].isdigit():
                has_day_token = True
                break
        if not has_day_token:
            # month-only
            year = dt.year
            month = dt.month
            from calendar import monthrange as _mr
            last_day = _mr(year, month)[1]
            return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"
        # Otherwise single day
        return dt.strftime("%Y-%m-%d"), dt.strftime("%Y-%m-%d")

    # If no tuples, try numeric-year detection for cases like 'entre 2022 et 2023'
    if not tuples:
        years = [int(t) for t in raw_tokens if len(t) == 4 and t.isdigit()]
        if len(years) >= 2:
            y1, y2 = min(years), max(years)
            return f"{y1}-01-01", f"{y2}-12-31"

    # Fallback: sliding-window approach to detect dates embedded inside noisy text
    # Tokenize by splitting on whitespace and punctuation
    import re as _re
    raw_tokens = [t for t in _re.split(r"[\s,;]+", text_original) if t]
    n = len(raw_tokens)
    for i in range(n):
        for j in range(i+1, min(i+7, n+1)):
            sub = ' '.join(raw_tokens[i:j])
            try:
                parsed_sub = search_dates(sub, languages=["fr", "en"], settings={"DATE_ORDER": "DMY"})
            except Exception:
                parsed_sub = None
            tuples = tuples_from_parsed(parsed_sub)
            if tuples:
                if len(tuples) >= 2:
                    dates = sorted([t[1] for t in tuples])
                    return dates[0].strftime("%Y-%m-%d"), dates[-1].strftime("%Y-%m-%d")
                match_text, dt = tuples[0]
                mt = match_text.strip()
                if mt.isdigit() and len(mt) == 4:
                    y = int(mt)
                    return f"{y:04d}-01-01", f"{y:04d}-12-31"
                tokens = [t.strip().lower() for t in mt.replace(',', ' ').split() if t.strip()]
                has_day_token = False
                for token in tokens:
                    if token.isdigit():
                        val = int(token) if token.isdigit() else None
                        if val and 1 <= val <= 31:
                            has_day_token = True
                            break
                    if token.endswith('er') and token[:-2].isdigit():
                        has_day_token = True
                        break
                if not has_day_token:
                    year = dt.year
                    month = dt.month
                    from calendar import monthrange as _mr
                    last_day = _mr(year, month)[1]
                    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"
                return dt.strftime("%Y-%m-%d"), dt.strftime("%Y-%m-%d")

    # Additional fallback: detect numeric hyphenated tokens like YYYY-MM-DD and parse them
    # with a safe string check (not regex) to avoid ambiguous parser behavior.
    # scan raw_tokens for 'YYYY-MM-DD'
    from datetime import datetime as _dt
    def try_parse_iso(token: str):
        if len(token) == 10 and token[4] == '-' and token[7] == '-':
            y = token[0:4]
            m = token[5:7]
            d = token[8:10]
            if y.isdigit() and m.isdigit() and d.isdigit():
                try:
                    _d = _dt.strptime(token, "%Y-%m-%d").date()
                    return _d
                except Exception:
                    return None
        return None

    iso_dates = []
    for tkn in raw_tokens:
        dt_iso = try_parse_iso(tkn)
        if dt_iso:
            iso_dates.append(dt_iso)
    if len(iso_dates) >= 2:
        iso_dates_sorted = sorted(iso_dates)
        return iso_dates_sorted[0].strftime("%Y-%m-%d"), iso_dates_sorted[-1].strftime("%Y-%m-%d")
    if len(iso_dates) == 1:
        return iso_dates[0].strftime("%Y-%m-%d"), iso_dates[0].strftime("%Y-%m-%d")

    return None, None


@tool
def get_time() -> str:
    """
    Get the current time in a human-readable string format.
    """
    current_time = datetime.now().strftime("%Hh%M")
    # Return a final answer sentence instead of just the raw time string
    return f"The current time is {current_time}."


@tool
def get_date() -> str:
    """
    Get the current date in a human-readable string format.
    """
    #print("Debug: get_date called",date.today())
    current_date = date.today().strftime("%d/%m/%Y")
    #print(f"Debug: current_date = {current_date}")
    return f"Today's date is {current_date}."


@tool
def calculator(expression: str) -> str:
    """
    Evaluate a simple arithmetic expression (e.g., '23 * 7').
    Expected format: 'number operator number'
    """
    try:
        cleaned = expression.strip().replace(" ", "")
        allowed_chars = set("0123456789+-*/.() ")
        if not all(c in allowed_chars for c in cleaned):
            return "Error: Disallowed characters in expression"
        return str(eval(cleaned))
    except Exception:
        return "Error: Invalid arithmetic expression"


@tool
def date_subtract(query: str) -> str:
    """
    Subtract a number of days from a date.
    Expected format: 'YYYY-MM-DD - days'
    Example: '2025-12-31 - 38' -> '2025-11-23'
    """
    try:
        match = re.search(r"\s*-\s*(\d+)\s*$", query)
        if not match:
            return "❌ Invalid format. Use: 'DATE - days'"
        days = int(match.group(1))
        # The date part is the query without the trailing '- days'
        date_part = query[:match.start()].strip()
        # Use dateparser.search.search_dates for flexible parsing
        try:
            parsed = search_dates(date_part, languages=["fr", "en"], settings={"DATE_ORDER": "DMY"})
        except Exception:
            parsed = None
        if not parsed:
            return "❌ Invalid date in query. Use a recognised date format like 'YYYY-MM-DD' or 'DD/MM/YYYY'"
        date_str = parsed[0][1].strftime("%Y-%m-%d")
        new_date = base_date - timedelta(days=days)

        return new_date.strftime("%Y-%m-%d")
    except Exception as e:
        return f"❌ Error: {str(e)}"


@tool
def adjust_date(user_input: str) -> str:
    """
    Accepts a date in 'YYYY-MM-DD' or 'DD/MM/YYYY' format and returns the previous day (formatted 'YYYY-MM-DD').
    """
    try:
        # Use search_dates for flexible input
        try:
            parsed = search_dates(user_input, languages=["fr", "en"], settings={"DATE_ORDER": "DMY"})
        except Exception:
            parsed = None
        if not parsed:
            return "❌ Invalid date format; supported: 'YYYY-MM-DD', 'DD/MM/YYYY', 'July 4, 2023', etc."
        dt = parsed[0][1]

        dt_prev = dt - timedelta(days=1)
        return dt_prev.strftime("%Y-%m-%d")
    except Exception as e:
        return f"❌ Error adjusting date: {str(e)}"


def extract_bbox_and_dates(user_input: str) -> dict:
    try:
        print(f"Debug: extract_bbox_and_dates called with input: {user_input}")
        # Ensure input is a string
        if not user_input:
            return {"error": "❌ Empty input string."}

        user_input_lower = user_input.lower()
        collection_map = {
            "sentinel-1": "sentinel-1-grd",
            "sentinel 1": "sentinel-1-grd",
            "sentinel-2": "sentinel-2-l2a",
            "sentinel 2": "sentinel-2-l2a",
            "modis": "firms-modis-c6",
            "viirs": "firms-viirs-nrt",
        }

        collection = None
        for key, val in collection_map.items():
            if key in user_input_lower:
                collection = val
                break

        if not collection:
            generic_terms = (
                "satellite",
                "satellites",
                "imagerie",
                "image satellite",
                "images satellite",
            )
            if any(term in user_input_lower for term in generic_terms):
                collection = "sentinel-2-l2a"
            else:
                return {
                    "error": "❌ Collection not recognized. Please specify: sentinel-1, sentinel-2, modis, viirs."
                }

        # --- LLM call to extract date and city ---
        system_prompt = """
        You are an assistant specialized in extracting structured information from user requests.
        Extract the start date, end date, and location (city, region, or country) from the user's text.
        Return ONLY a JSON object in this exact format:

        {
        "start_date": "YYYY-MM-DD" or null,
        "end_date": "YYYY-MM-DD" or null,
        "location": "city/region/country name" or null
        }

        Do NOT include any explanations, instructions, or extra text. 
        If a date is not specified, start_date and end_date should be null. If just one date is given, use it for both start_date and end_date.
        Always respond with valid JSON.
        """

        few_shot_examples = """
        Example 1:
        User input: "Show me satellite images of Paris in 2024"
        Response:
        {
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "location": "Paris"
        }

        Example 2:
        User input: "I need images from Tunisia between 2023-12-01 and 2023-12-10"
        Response:
        {
        "start_date": "2023-12-01",
        "end_date": "2023-12-10",
        "location": "Tunisia"
        }

        Example 3:
        User input: "Get satellite imagery of Nice"
        Response:
        {
        "start_date": null,
        "end_date": null,
        "location": "Nice"
        }
        
        Example 4:
        User input: "I was in italy last summer, show me satellite images there"
        Response:
        {
        "start_date": "2024-06-01",
        "end_date": 2024-08-31",
        "location": "Italy"
        }
        
        Example 5:
        User input: "there was a flood in luxembourg, show me satellite images there on july 15 2023"
        Response:
        {
        "start_date": "2023-07-15",
        "end_date": "2023-07-15",
        "location": "Luxembourg"
        }
        """

        llm = OllamaLLM(
            model="mistral",
            temperature=0.3,
            system_prompt=system_prompt
        )

        prompt = f"Extract start date, end date, and location from the following text as JSON. {few_shot_examples}\n User input: \"{user_input}\""
        llm_response = llm.invoke(prompt)
        print(f"Debug: LLM response: {llm_response}")
        import json
        try:
            extracted = json.loads(llm_response)
        except Exception:
            return {"error": f"❌ LLM response could not be parsed as JSON: {llm_response}"}

        start_date = extracted.get("start_date")
        end_date = extracted.get("end_date")
        city_name = extracted.get("location")
        if start_date is None or end_date is None:
            start_date, end_date = extract_dates_from_text(user_input)
        if not city_name:
            return {"error": "❌ Unable to determine location."}

        # --- Use existing get_city_bbox for bounding box ---
        bbox_result = get_city_bbox(city_name)
        if not bbox_result or len(bbox_result) != 5:
            return {"error": f"❌ Location '{city_name}' not found or bbox unavailable."}

        min_lon, min_lat, max_lon, max_lat, city_name_final = bbox_result
        if None in (min_lon, min_lat, max_lon, max_lat):
            return {"error": f"❌ Location '{city_name}' not found or bbox unavailable."}

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


def query_stac_with_retries(bbox_str, start_date_str, end_date_str, collection, query_func):
    """
    Interroge l'API STAC jusqu'à 3 fois en ajustant la fenêtre temporelle
    if no image is found.
    """
    max_attempts = 3
    attempt = 0
    date_format = "%Y-%m-%d"
    start_date = datetime.strptime(start_date_str, date_format)
    end_date = datetime.strptime(end_date_str, date_format)

    while attempt < max_attempts:
        params = f"{bbox_str} {start_date.strftime(date_format)} {end_date.strftime(date_format)} {collection}"
        result = query_func(params)

        if not isinstance(result, dict):
            return {
                "error": "Unexpected STAC response.",
                "details": result,
                "attempts": attempt + 1,
            }

        if result.get("error"):
            result["attempts"] = attempt + 1
            return result

        images = result.get("images") or result.get("features") or []
        if images:
            result["attempts"] = attempt + 1
            return result

        attempt += 1

        if attempt >= max_attempts:
            return {
                "message": result.get("message")
                or (
                    f"No images found for {collection} between {start_date.strftime(date_format)} "
                    f"and {end_date.strftime(date_format)} after several attempts."
                ),
                "collection": collection,
                "bbox": bbox_str,
                "start_date": start_date.strftime(date_format),
                "end_date": end_date.strftime(date_format),
                "images": result.get("images", []),
                "attempts": attempt,
            }

        if attempt == 1:
            end_date -= timedelta(days=1)
        elif attempt == 2:
            start_date -= timedelta(days=1)


import re as _re  # éviter conflit de nom avec le re global


@tool
def query_stac_catalog_with_retry(params: str) -> dict:
    """
    Wrapper pour interroger le catalogue STAC avec gestion de retries.
    Accepte :
    - Chaîne brute : "lon_min,lat_min,lon_max,lat_max start_date end_date collection"
    - Ou format clé=valeur : "lon_min=.. lat_min=.. lon_max=.. lat_max=.. start_date=.. end_date=.. collection=.."
    """
    try:
        if "=" in params:
            kv = dict(_re.findall(r"(\w+)=([^\s]+)", params))
            bbox_str = ",".join(
                [kv["lon_min"], kv["lat_min"], kv["lon_max"], kv["lat_max"]]
            )
            start_date = kv["start_date"]
            end_date = kv["end_date"]
            collection = kv["collection"]
        else:
            bbox_str, start_date, end_date, collection = params.split()

        return query_stac_with_retries(
            bbox_str, start_date, end_date, collection, query_stac_catalog
        )
    except Exception as e:
        return {"error": f"❌ Error in query_stac_catalog_with_retry: {str(e)}"}


def get_all_tools():
    """
    Return the list of all tools available to the agent.
    """
    return [
        get_date,
        get_time,
        calculator,
        query_stac_catalog,
        query_stac_catalog_with_retry,
        adjust_date,
        date_subtract,
        detect_fire_tool,
        query_disaster_events_tool,
        estimate_surface_water_ingress_tool,
        geo_info_tool,
        get_route_info,
        weather_tool,
        general_question_tool,
    ]