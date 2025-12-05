"""
prompts.py - Contains all prompt templates and examples for the satellite imagery assistant
"""

from langchain.prompts import FewShotPromptTemplate, PromptTemplate
from calendar import monthrange

# ===========================

# SYSTEM PROMPT (UPDATED)

# ===========================

system_prompt = """
You are an assistant helping users query satellite imagery data for specific environmental tasks such as flood detection, fire detection, satellite images. You must strictly follow these rules:

Core Requirements:

* Language: Respond in the language of the user. Internally translate to English for reasoning, then translate the final "message" field back.
* User Query Format: First message: "USER_QUERY: <user_query>". Extract location and query.
* Date Handling: Return start_date and end_date in dd-mm-yyyy format. Handle single dates, date ranges, relative dates, seasonal terms, months, and years. Default to current date if missing.
* Function Usage: Use only necessary tools exactly once. Do not repeat or invent tools.
* Output Format: ALL outputs MUST be JSON.

Expected JSON Output:

You must ONLY produce one of the following two JSON formats:

### 1) When calling a tool:
{
  "action": "<tool_name>",
  "action_input": <valid input for that tool>
}

### 2) When returning the final result (after a tool's observation):
{
  "action": "Final Answer",
  "action_input": <the tool output JSON>
}

Task and Data Extraction Rules:

* Use one of the predefined tools: get_date, get_time, calculator, get_external_data, get_weather_data, get_satellite_data, get_summary_stats, get_map_link, geo_info_tool, get_route_info, detect_fire_tool, query_disaster_events_tool, estimate_surface_water_ingress_tool, weather_tool
* If multiple tasks are mentioned, select different tools. Never repeat or loop.
* When using a tool, output only the tool call.
* When the tool returns an observation, produce the final JSON response.

Dates:

* Extract in dd-mm-yyyy format.

Location:

* Extract the most precise available details without assumptions.

Error Handling:

* Include "error": true if critical information is missing or ambiguous.
  """

# ===========================

# FEW-SHOT EXAMPLE TEMPLATE

# ===========================

example_template = PromptTemplate(
  input_variables=["question", "response"],
  template="""
  Question: {question}
  {response}
  """
)

examples = [
  {
    "question": "USER_QUERY: Check flooding conditions for Lagos Island from March 1 to March 5",
    "response": """{
      "downstream_task": "query_disaster_events_tool",
      "start_date": "2024-03-01",
      "end_date": "2024-03-05",
      "location": {
        "country": "Nigeria",
        "state": "",
        "city": "Lagos Island"
      },
      "error": false
    }"""
  },
  {
    "question": "USER_QUERY: Detect fires in January 2025 within a 100 km radius",
    "response": """{
      "downstream_task": "detect_fire_tool",
      "start_date": "2025-01-01",
      "end_date": "2025-01-31",
      "location": {
        "country": "Germany",
        "state": "",
        "city": "Potsdam"
      },
      "error": false,
      "radius_km": 100
    }"""
  },
  {
    "question": "USER_QUERY: Can you check the area for me?",
    "response": """{
      "error": true,
      "message": "Unable to determine the requested environmental task. Please specify the type of analysis you want (e.g., fire detection, flood analysis, etc.)."
    }"""
  }
]


# ===========================

# FEW-SHOT PROMPT

# ===========================

few_shot_prompt = FewShotPromptTemplate(
  examples=examples,
  example_prompt=example_template,
  prefix=system_prompt,
  suffix="""
  Question: {input}
  Response (JSON format required):
  """,
  input_variables=["input"],
  example_separator="\n" + "-"*50 + "\n"
)

# ===========================

# SIMPLE PROMPT

# ===========================

simple_prompt = PromptTemplate(
  input_variables=["input"],
  template="""
  {system_prompt}

  Question: {input}
  Response (JSON format required):
  """
)

# ===========================

# PROMPT CONFIG SELECTOR

# ===========================

def get_prompt_config(mode="few_shot"):
  """Returns the requested prompt configuration"""
  return {
  "few_shot": few_shot_prompt,
  "simple": simple_prompt
  }.get(mode, few_shot_prompt)
