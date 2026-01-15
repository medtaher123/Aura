# GeoServer (WFS + WMS) Agent Integration Report

Date: 2025-12-17

## Goal
Enable the agent to:
1) Decide when a user request should be answered using GeoServer.
2) Query GeoServer polygons with filters (WFS), and
3) Display the resulting “mask” on an interactive map (Folium), using either:
   - GeoJSON overlay (from WFS) for smaller result sets, or
   - WMS raster tiles for fast visualization.

This work targets the existing Streamlit UI flow and the LangChain tool-selection agent.

---

## What Was Implemented

### 1) New GeoServer Tool: WFS filtering + Map rendering
File: `src/tools/risk_geoserver.py`

A new LangChain tool was added:
- `geoserver_risk_mask_tool(query_text: str) -> dict`

What it does end-to-end:
- Uses an LLM extraction prompt to turn the user request into structured filters (risk type, date range, confidence, bbox/location, etc.).
- Builds a GeoServer `CQL_FILTER` string.
- Calls GeoServer **WFS** `GetFeature` (`outputFormat=application/json`) to retrieve matching polygons.
- Computes a summary:
  - feature count
  - total area (if available)
  - average confidence
  - geometry bounds (for auto-zoom)
- Generates a Folium map saved into `src/maps/` with a timestamp name:
  - `RiskMask_YYYYMMDD_HHMMSS.html`
- Renders in two modes:
  - `geojson` mode: render returned polygons directly (better interactivity)
  - `wms` mode: render filtered WMS tiles (better performance for large results)
  - `auto` mode: GeoJSON if <= 200 features, else WMS

Configuration knobs:
- `GEOSERVER_BASE_URL` environment variable
- `GEOSERVER_RISK_LAYER` environment variable

Default values currently used:
- GeoServer base URL: `http://geoserver-alb-556624184.eu-west-3.elb.amazonaws.com/geoserver`
- Layer: `georisk:predictions`

### 2) Contracts for GeoServer risk queries
File: `src/tools/contracts.py`

Added a dedicated Pydantic model:
- `GeoServerRiskQuery`

It captures the fields the agent/tool extraction supports:
- `risk_type`, `region`, `location`, `bbox`
- `start_date`, `end_date`
- `min_confidence`, `min_area_m2`
- `model_name`, `model_version`
- `limit`, `render_mode`

### 3) Tool registration so the agent can call it
File: `src/tools/tools_risk.py`

- Imported `geoserver_risk_mask_tool`
- Added it to `get_all_tools()` so the agent executor sees it.

### 4) Prompt allow-list updated
File: `src/core/prompts.py`

- Added `geoserver_risk_mask_tool` to the “Use one of the predefined tools” list.

This is important because your system prompt explicitly restricts tools the agent is allowed to call.

---

## Files Created vs Modified

### Created
- No brand-new Python modules were created during this change set.

### Modified
- `src/tools/risk_geoserver.py`
- `src/tools/contracts.py`
- `src/tools/tools_risk.py`
- `src/core/prompts.py`

---

## How to Use (User Examples)
Once the agent runtime is available, example UI prompts:
- “Show GeoServer risk mask in Tunis with confidence > 0.7”
- “Display risk polygons for region Ariana between 2025-12-01 and 2025-12-10”
- “Show risk_type water in test-region”

Expected tool output includes:
- `map_file`: `RiskMask_....html`

The Streamlit UI already renders `.html` map files if returned.

---

## Pros
- **Correct protocol split**: WFS is used for filtering/reasoning; WMS is used for fast rendering.
- **Flexible filtering**: supports common attributes (`risk_type`, `region`, `model_name`, `model_version`, `confidence`, `inference_date`) and spatial filtering (`BBOX(geom, ...)`).
- **Auto rendering strategy**: GeoJSON for small results (interactive), WMS for large results (performance).
- **Minimal integration surface**: only needed registration in the tool list + allow-list in the prompt.
- **Environment-configurable**: base URL and layer name can be overridden without code changes.

---

## Cons / Limitations (Current)
- **Requires Ollama to run**: the agent and the tool’s parameter extraction uses `OllamaLLM(model="mistral")`. If Ollama isn’t installed/running on `localhost:11434`, Streamlit will error with connection refused.
- **Double network call**: by design it calls WFS first (for bounds + summary) even if final rendering is via WMS.
- **Filter extraction is LLM-based**: accuracy depends on prompt quality and the model; some user phrasing may not map to the right fields.
- **No automated tests added yet** for:
  - CQL building
  - WFS request construction
  - map generation output shape
- **Date parsing assumptions**: the tool accepts `YYYY-MM-DD` or ISO; it does not (yet) robustly parse “last week”, “yesterday”, etc.

---

## Future Enhancements

### High value / short term
1) **Add tests (mocked HTTP)**
   - Unit test CQL building (`_build_cql_filter`)
   - Mock WFS responses and assert output includes `map_file`, correct `cql_filter`, and reasonable summary

2) **Improve extraction reliability**
   - Add few-shot examples for:
     - “last week / last month” date phrases
     - bbox input variants
     - risk_type normalization (e.g., “flood” → “water” if that’s your taxonomy)

3) **Support WMS-only mode**
   - If you ever have layers that are WMS-only, add a mode that skips WFS and still renders.

4) **Better error messages**
   - Distinguish between “LLM backend not reachable” vs “GeoServer request failed” vs “no features found”.

### Medium term
5) **Pagination for WFS**
   - Use `startIndex` + `count` (WFS 2.0) when result sets are large.

6) **Caching**
   - Cache WFS results per query/filter to avoid repeated calls during chat iterations.

7) **Richer map UX (still minimal)**
   - Add per-feature popup fields you care about (`tile_id`, `inference_date`, `extra_info`).

---

## Notes / Environment
- Confirmed externally (from this machine) that GeoServer WFS is enabled and returns `georisk:predictions` features.
- Streamlit failures seen during manual runs were caused by Ollama not being installed/running, not by GeoServer.
