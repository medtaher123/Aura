from langchain_ollama import OllamaLLM


def extract_params_from_text(text: str):
    """
    Extracts start_date, end_date, city/location, country, radius and disaster_type using a single LLM call.
    Returns: (start_date, end_date, location, country, radius_km, disaster_type)
    """
    if not text:
        return None, None, None, 100

    # --- Build LLM extraction prompt ---
    system_prompt = """
    You are an expert system that extracts structured data from natural language.
    Your job is to identify:
    - start_date (YYYY-MM-DD or null)
    - end_date (YYYY-MM-DD or null)
    - location (city, region, or country)
    - country (from city or country names mentioned)
    - radius_km (integer or null)
    - disaster_type (fire, flood, storm, earthquake, extreme temperature, drought, industrial accident, transport)
    
    RULES:
    - If only one date is mentioned, set start_date = end_date.
    - If a year is mentioned alone (e.g. "in 2022"), return full year range.
    - If a month is mentioned ("in July 2023"), return first and last day.
    - If a season is mentioned (winter, summer, etc.), use:
        * winter: Dec 1 – Feb 28
        * spring: Mar 1 – May 31
        * summer: Jun 1 – Aug 31
        * autumn/fall: Sep 1 – Nov 30
    - If radius is not mentioned, return null.
    - Don't infer missing info; return null if not specified.
    - ALWAYS answer with pure JSON. NO explanations.
    """

    few_shot = """
    Example 1:
    User input: "fires in Marseille 2025-01 - 250"
    Response:
    {
      "start_date": "2025-01-01",
      "end_date": "2025-01-31",
      "location": "Marseille",
      "country": "France",
      "radius_km": 250,
      "disaster_type": "fire"
    }

    Example 2:
    User input: "earthquake in Tunis summer 2024"
    Response:
    {
      "start_date": "2024-06-01",
      "end_date": "2024-08-31",
      "location": "Tunis",
      "country": "Tunisia",
      "radius_km": null,
      "disaster_type": "earthquake"
    }

    Example 3:
    User input: "Rome December 1st to December 10th 2023 floods"
    Response:
    {
      "start_date": "2023-12-01",
      "end_date": "2023-12-10",
      "location": "Rome",
      "country": "Italy",
      "radius_km": null,
      "disaster_type": "flood"
    }

    Example 4:
    User input: "Morocco"
    Response:
    {
      "start_date": null,
      "end_date": null,
      "location": "Morocco",
      "country": "Morocco",
      "radius_km": null,
      "disaster_type": null
    }
    """

    # --- Invoke LLM ---
    llm = OllamaLLM(model="mistral", temperature=0.1, system_prompt=system_prompt)
    prompt = f'{few_shot}\nUser input: "{text}"\nReturn JSON:'
    llm_response = llm.invoke(prompt)

    import json

    try:
        data = json.loads(llm_response)
    except Exception:
        return {"error": f"❌ LLM returned invalid JSON: {llm_response}"}

    # --- Extract fields ---
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    location = data.get("location")
    country = data.get("country")
    disaster_type = data.get("disaster_type")
    radius_km_raw = data.get("radius_km")
    if radius_km_raw is None or radius_km_raw == "":
        radius_km = 100
    else:
        try:
            radius_km = int(float(radius_km_raw))
        except (TypeError, ValueError):
            radius_km = 100

    return start_date, end_date, location, country, radius_km, disaster_type

