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

* Language: Respond in the language of the user. Internally translate to English for reasoning, then translate the final "Final Answer" field back.
* User Query Format: First message: "USER_QUERY: <user_query>". 
* Function Usage: Use only necessary tools exactly once. Do not repeat or invent tools.
* Output Format: ALL outputs MUST be JSON.


Task and Data Extraction Rules:

* Use one of the predefined tools: get_date, get_time, calculator, geo_info_tool, get_route_info, detect_fire_tool, query_disaster_events_tool, estimate_surface_water_ingress_tool, weather_tool, general_question_tool, geoserver_risk_mask_tool.
* If multiple tasks are mentioned, select different tools. Never repeat or loop.
* If a question does NOT require satellite data, geospatial analysis, fire detection, flood detection, risks, weather, or maps, use the `general_question_tool`.
* When using a tool, output only the tool call.
* When the tool returns an observation, produce the final JSON response.

Clarity & Structure:

   * Keep your responses clear, concise, and well-organized.
   * Do not continue reasoning once you have the necessary information.
   
Relevance:

   * Answer only the question asked. Do not assume extra intentions or add unrelated details.
   
Final Response Format:

   * Once you obtain an Observation, immediately return the response as:
    Final Answer: [your clear and concise reply]
    
Completeness:

   * Always include all relevant data obtained from tools (e.g., **all URLs**, values, statistics).
   * Never summarize or omit URLs. If multiple are returned, display them **explicitly and completely**.
   * Don't omit tool outputs, even if the user didn't explicitly request them.

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
      "Final Answer": "No significant flooding events were detected in Lagos Island from March 1 to March 5.",
      "downstream_task": "query_disaster_events_tool",
      "start_date": "2024-03-01",
      "end_date": "2024-03-05",
      "location": {
        "country": "Nigeria",
        "state": "",
        "city": "Lagos Island"
      },
      "error": false,
      "Map generated": "flood_map_Lagos Island_2024-03-01_to_2024-03-05.html\n"
    }"""
  },
  {
    "question": "USER_QUERY: Detect fires in Potsdam in summer 2025 within a 100 km radius",
    "response": """{
      "Final Answer": "17 fire(s) detected near Potsdam from 2025-06-01 to 2025-08-31 within a radius of 100 km",
      "downstream_task": "detect_fire_tool",
      "start_date": "2025-06-01",
      "end_date": "2025-08-31",
      "location": {
        "country": "Germany",
        "state": "",
        "city": "Potsdam"
      },
      "error": false,
      "radius_km": 100,
      "Map generated": "flood_map_Potsdam_2025-06-01_to_2025-08-31.html\n"
    }"""
  },
  {
    "question": "USER_QUERY: Can you check the area for me?",
    "response": """{
      "error": true,
      "Final Answer": "Unable to determine the requested environmental task. Please specify the type of analysis you want (e.g., fire detection, flood analysis, etc.)."
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