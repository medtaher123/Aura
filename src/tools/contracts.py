# tools/contracts.py
from pydantic import BaseModel
from typing import List, Literal, Optional

class RiskQuery(BaseModel):
    risk_type: str
    region: Optional[str]
    bbox: Optional[List[float]]  # [min_lon, min_lat, max_lon, max_lat]

class GeoServerQuery(RiskQuery):
    layer_name: str  # Name of the GeoServer layer to query


class GeoServerRiskQuery(BaseModel):
    layer_name: str = "georisk:predictions"
    risk_type: Optional[str] = None
    region: Optional[str] = None
    location: Optional[str] = None
    bbox: Optional[List[float]] = None  # [min_lon, min_lat, max_lon, max_lat]
    start_date: Optional[str] = None  # YYYY-MM-DD or ISO timestamp
    end_date: Optional[str] = None  # YYYY-MM-DD or ISO timestamp
    min_confidence: Optional[float] = None
    min_area_m2: Optional[float] = None
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    limit: int = 500
    render_mode: Literal["auto", "wms", "geojson"] = "auto"
