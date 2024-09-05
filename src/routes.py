from os import getenv
from dotenv import load_dotenv

from datetime import datetime as dt, timedelta as tdelta, timezone as tz
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup as BSoup
from googlemaps import Client as Maps
from html import unescape
from requests import get, JSONDecodeError

from src.helpers import ICON_HI, URLS, get_tz, gen_response, icon_wx
from src.almanac_mthds import get_lunar, get_solar
from src.current_mthds import get_ndfd, get_synoptic, finalize_current
from src.forecast_mthds import get_nbm, parse_nbm

load_dotenv()

def forward(address):
    # Get geodata, return error code if missing data/failure
    try:
        data = Maps(getenv("MAPS_KEY")).geocode(address)[0]
        geo_comps, ad_comps = data["geometry"]["location"], data["address_components"]
        lat, lon = geo_comps["lat"], geo_comps["lng"]
    except (IndexError, KeyError, TypeError): return gen_response("google")

    get_comp = lambda cs: [x for x in ad_comps if any([y in x["types"] for y in cs])] or None
    i0or_none = lambda cs: get_comp(cs)[0] if get_comp(cs) else None

    # Get location elems by type-priority
    poi = i0or_none(["point_of_interest"])
    prem = i0or_none(["subpremise", "premise"])
    nbhd = i0or_none(["neighborhood", "neighbourhood"])
    state = i0or_none(["administrative_area_level_1", "country"])
    city = i0or_none([f"sublocality_level_{x}" for x in reversed(range(1, 5))] + [
        "sublocality", "colloquial_area", "locality", "administrative_area_level_3"
    ])

    # Location format groups by priority
    loc_groups = [[poi, city], [prem, city], [nbhd, city], [city, state], [city], [state]]
    loc_groups = [x for x in loc_groups if all(x)]
    loc = ", ".join([x["short_name"] for x in loc_groups[0]]) if loc_groups else None

    return gen_response({"lat": lat, "lon": lon, "loc": loc, "tz": get_tz(lat, lon)})

def reverse(lat, lon):
    try: data = get(
        URLS["nominatim"], headers=eval(getenv("PERSONAL_USER_AGENT")), 
        params={"lat": lat, "lon": lon, "format": "geojson"}
    ).json()["features"][0]["properties"]["address"]
    except (JSONDecodeError, KeyError, TypeError): gen_response("nominatim")

    targets = [
        "city_block", "subdivision", "neighbourhood", "quarter", 
        "suburb", "borough", "village", "town", "city", "municipality", 
        "county", "region", "state", "postcode", "country"
    ]

    return gen_response({"address": ", ".join([data[x] for x in targets if x in data])})

def alerts(lat, lon):
    # Returns active weather alerts collected from the NWS MapClick API
    payload = {"lat": lat, "lon": lon, "unit": 0, "lg": "english", "FcstType": "json"}

    try: 
        data = get(URLS["mapclick"], payload).json()
        zdata, adata = data["location"], data["data"]["hazardUrl"]
    except (JSONDecodeError, KeyError): return gen_response("nws_mapclick")

    # Get alert zones and alerts or boilerplate "no alerts"
    zones = ", ".join([zdata[x] for x in zdata if x in ["zone", "firezone", "county"]])
    alerts = [a.text for a in [BSoup(get(unescape(l)).text, "lxml").pre for l in adata] if a]
    alerts = alerts or ["There are no active watches, warnings or advisories."]
    alerts = ["<pre class='alert-entry'>" + a.replace("\n", "&#10;") + "</pre>" for a in alerts]

    msg = {"zones": zones, "alerts": alerts}

    return gen_response(msg)

def almanac(lat, lon):
    tz = ZoneInfo(get_tz(lat, lon))
    date = dt.now(tz=tz)

    return gen_response({
        "solar": get_solar(lat, lon, tz, date), 
        "lunar": get_lunar(lat, lon, tz, date)
    })

def current(lat, lon):
    msg = {**{"stations": []}, **{x: None for x in [
        "t", "rh", "dew", "wind", "vis", "p", "ceil", "heat", 
        "wbgt", "chill", "wx", "icon", "wspeed", "wgust", "wdir"
    ]}}

    # Get NDFD data, return error if request failed
    msg = get_ndfd(lat, lon, msg)
    if msg == 500: return gen_response("ndfd")

    # Get Synoptic data, return error if request failed
    msg = get_synoptic(lat, lon, msg)
    if msg == 500: return gen_response("synoptic")

    # 
    msg["stations"] = list(set(filter(None, msg["stations"])))
    
    return gen_response(finalize_current(msg, lat, lon))

def forecast(lat, lon):
    # Returns forecasted weather data from the National Blend of Models
    # Short and Extended products (NBS and NBE respectively)
    # See details here: https://vlab.noaa.gov/web/mdl/nbm-textcard-v4.1
    day_range, products = 3, ["nbe", "nbs"]

    # Get bulletins, return error response if any bulletin requests failed
    bulletins = {p: get_nbm(lat, lon, p)[0] for p in products}
    if any([type(x) != dict for x in bulletins.values()]): return gen_response("nbm_text")

    # Determine local start date and convert to UTC
    local_sd = (dt.now(tz=ZoneInfo(get_tz(lat, lon))) + tdelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    utc_sd = dt.utcfromtimestamp(local_sd.timestamp()).replace(tzinfo=tz.utc)

    # Group bulletin data by local day and parse
    msg = []
    for x in range(day_range):
        conds, temps, start = [], [], utc_sd + tdelta(hours=(24 * x))

        for hr in [start + tdelta(hours=x) for x in range(24)]:
            hdata = None
            if hr in bulletins["nbs"]: hdata = parse_nbm(bulletins["nbs"][hr])
            elif hr in bulletins["nbe"]: hdata = parse_nbm(bulletins["nbe"][hr])
            
            if hdata: conds.append(hdata["name"]), temps.append(hdata["t"])

        day_cond = max(conds, key=lambda x: ICON_HI[x]) if conds else "skc"

        msg.append({**{
            "hi": round(max(temps)) if temps else None, 
            "lo": round(min(temps)) if temps else None,
            "wday": (local_sd + tdelta(days=x)).strftime("%a").upper()
        }, **icon_wx(lat, lon, day_cond)})

    return gen_response(msg)
     