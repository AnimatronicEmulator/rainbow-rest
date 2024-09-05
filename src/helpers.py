from datetime import datetime as dt, timezone as tz
import inspect
import json
from math import exp
from re import findall, search

from astral import LocationInfo as Loc
from astral.sun import sun
from flask import jsonify, Response
from timezonefinder import TimezoneFinder

# datamaps_dir = "/home/animatronic/mysite/static/data_maps/"
# with open(datamaps_dir + "icons.json") as f: ICONS = json.load(f)
# with open(datamaps_dir + "NBMstations.json") as f: STATIONS = json.load(f)
with open("static/data_maps/icons.json") as f: ICONS = json.load(f)
with open("static/data_maps/NBMstations.json") as f: STATIONS = json.load(f)
ICON_HI = {k: v["hierarchy"] for k, v in ICONS.items()}

# Bounding boxes US regions. Format: minlat, maxlat, minlon, maxlon
US_BBOXS = {
    "ak": (51.214183, 71.365162, -179.148909, 179.77847),
    "co": (24.7433195, 49.3457868, -124.7844079, -66.9513812),
    "gu": (13.234189, 13.7061790, 144.618068, 145.0091670),
    "hi": (18.8654600, 28.5172690, -178.334698, -154.80833743387433), 
    "pr": (17.7306659, 18.6663822, -68.1109184, -65.22314866408664)
}

# Status codes
CODES = {
    "InvalidPoint": {"n": "InvalidPoint", "c": 461, "d": "lat and lon arguments must be float values corresponding to a geopoint within the US including AK, GU, HI, and PR"},
    "InvalidAddress": {"n": "InvalidAddress", "c": 462, "d": "The address argument must be a string corresponding to a location within the US including AK, GU, HI, and PR; e.g., 'Bushwick, Brooklyn'"},
    "google": {"n": "GoogleGeocodeAPIError", "c": 521, "d": "The Google Maps Geocoding API request failed"},
    "nbm_text": {"n": "NBMRequestFailed", "c": 522, "d": "The NOMADS request for the NBM text bulletin request failed"},
    "ndfd": {"n": "NDFDAPIError", "c": 523, "d": "The NDFD XML API request failed"},
    "nominatim": {"n": "NominatimAPIError", "c": 524, "d": "The OpenStreetMap Nominatim API request failed"},
    "synoptic": {"n": "SynopticAPIError", "c": 525, "d": "The Synoptic Data API request failed"},
    "nws_mapclick": {"n": "NWSMapClickAPIError", "c": 526, "d": "The NWS MapClick API request failed"},
}

URLS = {
    "nbm": "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.%(d)s/%(h)s/text/blend_%(p)stx.t%(h)sz",
    "syn": "https://api.synopticdata.com/v2/stations/latest",
    "nominatim": "https://nominatim.openstreetmap.org/reverse", 
    "mapclick": "https://forecast.weather.gov/MapClick.php",
    "ndfd": "https://digital.mdl.nws.noaa.gov/xml/sample_products/browser_interface/ndfdXMLclient.php",
}

def validate(route, lat=None, lon=None, address=None):
    # Check that address is a string or a zipcode (long or short)
    val_address = type(address) == str or len(str(address)) in (5, 9)

    # Check that both lat and lon exist and within one bbox from US_BBOXS
    val_latlon = type(lat) == type(lon) == float and any([
        (x[0] <= lat <= x[1]) and (x[2] <= lon <= x[3]) for x in US_BBOXS.values()
    ])

    if route == "forward": return 200 if val_address else "InvalidAddress"
    else: return 200 if val_latlon else "InvalidPoint"

def gen_response(data):
    # Returns API response including JSON data and HTTP status code
    if type(data) != str: return jsonify(data)

    code, ctype = f'{CODES[data]["c"]} {CODES[data]["n"]}', "string"
    return Response(data, headers={"Content-Type": ctype}), code

def isnum(x):
    # Helper method to quickly determine if a value is numeric
    if type(x) in (bool, None): return None
    try: return float(x)
    except (ValueError, TypeError): return None

def icon_wx(lat, lon, name=None, link=None):
    # Returns day/night accurate icon url from icons using astral

    # Calculate day or night value
    if inspect.stack()[1][3] == "finalize_current":
        date = dt.now(tz=tz.utc)
        s = sun(Loc("", "", "", lat, lon).observer, date)
        daynite = "day" if (s["sunrise"] < date < s["dusk"]) else "night"
    else: daynite = "day"

    # Parse link for icon name
    if link and not name:
        if "DualImage" in link:
            names = findall(r"(?<=\?[a-z]{1}=)\w+(?=&)|(?<=&[a-z]{1}=)\w+(?=&)", link)
            name = max(names, key=lambda x: ICON_HI[x]) if names else "skc"
        else:
            try: name = search(r"\D+", search(r"(?<=/)\w+(?=\.[a-z]{3}$)", link).group(0)).group(0)
            except: name = "skc"
    elif not name: name = "skc"

    return {"icon": ICONS[name][daynite], "wx": ICONS[name]["description"]}

def get_tz(lat, lon):
    # Helper method that returns the timezone using timezonefinder
    return TimezoneFinder().timezone_at(lat=lat, lng=lon)

def get_hix(t, rh):
    # Returns heat index if relevant. Source:
    # Anderson, G Brooke et al. “Methods to calculate the heat index as an exposure 
    # metric in environmental health research.” Environmental health perspectives 
    # vol. 121,10 (2013): 1111-9. doi:10.1289/ehp.1206273
    c1, c2, c3 = -42.379, 2.04901523, 10.14333127
    c4, c5, c6 = -0.22475541, -6.83783e-3, -5.481717e-2
    c7, c8, c9 = 1.22874e-3, 8.5282e-4, -1.99e-6

    hix = c1 + (c2 * t) + (c3 * rh) + (c4 * t * rh)
    hix += (c5 * t ** 2) + (c6 * rh ** 2) + (c7 * t ** 2 * rh)
    hix += (c8 * t * rh ** 2) + (c9 * t ** 2 * rh ** 2)

    return round(hix) if hix >= 95 else None

def get_chill(t, ws):
    # Returns wind chill if relevant 
    # Model from the National Weather Service
    c1, c2, c3, c4 = 35.74, 0.6125, 35.75, 0.427

    wc = c1 + (c2 * t) - (c3 * ws ** 0.16) + (c4 * t * ws ** 0.16)
    return round(wc) if wc <= -18 else None

def get_rh(t, dpt):
    # Returns relative humidity. Source:
    # Alduchov, Oleg; Eskridge, Robert (1997-11-01), Improved Magnus' Form 
    # Approximation of Saturation Vapor Pressure, NOAA, doi:10.2172/548871
    t, dpt = (t - 32) * (5 / 9), (dpt - 32) * (5 / 9)
    l, b = 243.04, 17.625

    return 100 * ((exp((b * dpt) / (l + dpt)) / exp((b * t) / (l + t))))

def wx_calcs(t=None, ws=None, rh=None, dpt=None):
    # Returns a dict with heat index, wind chill, and relative humidity
    response = {} if rh else {"rh": None}

    # Calculate relative humidity if necessary
    if not rh and t and dpt: rh = response["rh"] = get_rh(t, dpt)

    # Calculate heat index
    response["heat"] = get_hix(t, rh) if t and rh else None
    
    # Calculate wind chill
    response["chill"] = get_chill(t, ws) if t and ws else None

    return response
