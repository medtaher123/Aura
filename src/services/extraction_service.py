#extraction_service.py
# Extraction service module - handles extraction of data from text
# Can be extended with more extraction utilities

def extract_location_from_text(text: str) -> str:
    """Extract location name from text"""
    import re
    location_keywords = [
        r'\b(?:near|in|at|around)\s+([A-Za-z\s]+?)(?:\s+from|\s+between|\s+during|$)',
        r'^([A-Za-z\s]+?)\s+(?:from|between|during)',
        r'^\s*(\w+(?:\s+\w+)*)\s*$'
    ]
    for pattern in location_keywords:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None
