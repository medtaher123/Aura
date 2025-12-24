# tests/test_tools_geocode.py
from src.tools import tools_geocode as geo

def test_get_city_bbox_ok(mocker):
    mock_resp = mocker.Mock()
    mock_resp.json.return_value = [{
        "boundingbox": ["33.0","34.0","-8.0","-7.0"],
        "display_name": "Casablanca, Maroc"
    }]
    mocker.patch("src.tools.tools_geocode.requests.get", return_value=mock_resp)

    lon_min, lat_min, lon_max, lat_max, name = geo.get_city_bbox("Casablanca")
    assert (lon_min, lat_min, lon_max, lat_max) == (-8.0, 33.0, -7.0, 34.0)
    assert name == "Casablanca"

def test_get_city_bbox_empty(mocker):
    mock_resp = mocker.Mock()
    mock_resp.json.return_value = []
    mocker.patch("src.tools.tools_geocode.requests.get", return_value=mock_resp)

    a,b,c,d,name = geo.get_city_bbox("Nowhere")
    assert (a,b,c,d) == (None, None, None, None)
    assert name == "Nowhere"
