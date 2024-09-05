from os import getenv
from dotenv import load_dotenv
from datetime import datetime as dt, timedelta as tdelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup as BSoup
from requests import get, JSONDecodeError

from src.helpers import URLS, get_tz, icon_wx, isnum, wx_calcs


load_dotenv()

def get_ndfd(lat, lon, msg):
    # Get NDFD-NWS station ID
    tz = ZoneInfo(get_tz(lat, lon))
    date = dt.now(ZoneInfo(get_tz(lat, lon)))

    # Maps msg keys to NDFD req. parameters and XML tags
    data_map = {
        "t": {"name": "temperature", "param": "temp", "attrs": {"type": "hourly"}}, 
        "dew": {"name": "temperature", "param": "dew", "attrs": {"type": "dew point"}}, 
        "wbgt": {"name": "temperature", "param": "wbgt", "attrs": {"type": "wet bulb globe"}}, 
        "wspeed": {"name": "wind-speed", "param": "wspd", "attrs": {"type": "sustained"}}, 
        "wgust": {"name": "wind-speed", "param": "wgust", "attrs": {"type": "gust"}}, 
        "wdir": {"name": "direction", "param": "wdir", "attrs": {"type": "wind"}}, 
        "rh": {"name": "humidity", "param": "rh", "attrs": {"type": "relative"}}, 
        "icon": {"name": "conditions-icon", "param": "icons"}, 
        "ceil": {"name": "ceiling", "param": "ceil"}
    }

    vars = {v["param"]: v["param"] for v in data_map.values()}
    dates = {k: v.replace(minute=0, second=0).isoformat(timespec="seconds") for k, v in 
        {"begin": date - tdelta(hours=1), "end": date + tdelta(hours=2)}.items()
    }

    # Make request for NDFD data
    data = BSoup(get(URLS["ndfd"], {
        "lat": lat, "lon": lon, "product": "time-series", **vars, **dates
    }).text, "xml")

    # Collect idxs of target date and limit data or return error
    try: 
        svts = {t.find("layout-key").text: [
            dt.fromisoformat(x.text).replace(tzinfo=tz)
            for x in t.find_all("start-valid-time")
        ] for t in data.find_all("time-layout")}

        idxs = {k: v.index(min(v, key=lambda x: abs(x - date))) for k, v in svts.items()}
        data = data.find("parameters")
    except: return 500

    # Return error if date-indexing failed
    if not (all([svts, data, idxs]) and len(svts) == len(idxs)): return 500

    # Parse NDFD data
    for k, v in data_map.items():
        child = "value" if k != "icon" else "icon-link"

        item = data.find(**{x: y for x, y in v.items() if x != "param"})
        try: item = item.find_all(child)[idxs[item.attrs["time-layout"]]].text
        except: item = None

        if k == "ceil" and item: item = isnum(item) or item.title()
        elif k != "icon" and item: item = isnum(item)

        msg[k] = item

    # Get station id from NWS
    try: msg["stations"].append(get(URLS["mapclick"], {
        "lat": lat, "lon": lon, "units": 0, "lg": "english", "FcstType": "json"
    }).json()["location"]["metar"])
    except (JSONDecodeError, KeyError, ValueError): pass

    return msg

def get_synoptic(lat, lon, msg):
    skey, vkey, okey, syn_map = "STATION", "SENSOR_VARIABLES", "OBSERVATIONS", {
        "t": "air_temp", "ceil": "ceiling", "vis": "visibility", "p": "pressure", 
        "wgust": "wind_gust", "wspeed": "wind_speed", "rh": "relative_humidity",
        "wdir": "wind_cardinal_direction", "dew": "dew_point_temperature"
    }

    payload = {
        "token": getenv("SYNOPTIC_TOKEN"), "limit": 5, "status": "active",
        "units": "english,pres|inhg", "vars": ",".join([x for x in syn_map.values()]),
        "radius": f"{lat},{lon},20", "within": 60
    }

    # Make request for synoptic data, return error if necessary
    try: data = get(URLS["syn"], payload).json()[skey]
    except (JSONDecodeError, KeyError): return 500

    # data to dict with (k, ⌊stn w/ v⌉ or v) pairs
    st0orv = lambda st, v: st[0] if st else v
    data = {k: st0orv([s for s in data if v in s[vkey]], v) for k, v in syn_map.items()}

    # Assemble missing vars and make unique query for each
    mia = {k: v for k, v in data.items() if not msg[k] and type(v) == str}

    for k, v in mia.items():
        payload["vars"], payload["limit"] = v, 1
        try: data[k] = get(URLS["synoptic"], payload).json()[skey][0]
        except (JSONDecodeError, KeyError, IndexError): pass

    # Parse data
    for k, st in data.items():
        if type(st) == str: continue
        value = st[okey][list(st[vkey][syn_map[k]].keys())[0]]["value"]

        # Add value/stid to msg; wdir in cardinal dirs.
        msg[k] = value if k == "wdir" else isnum(value)
        msg["stations"].append(st["STID"])

    # Filter out redundant or superfluous stids
    msg["stations"] = list(set(filter(None, msg["stations"])))

    return msg

def finalize_current(msg: dict, lat, lon):
    # Returns the response data formatted to match WeatherStar 4000 output

    fmt = lambda x, y: f"{round(msg[x])}{y}" if type(msg[x]) == float else None

    # Get icon, wx description, heat index, wind chill and any remaining formatting
    msg.update(icon_wx(lat, lon, link=msg["icon"]))
    msg.update(wx_calcs(msg["t"], msg["wspeed"], msg["rh"], msg["dew"]))
    msg.update({
        "t": fmt("t", "&deg;"), "dew": fmt("dew", "&deg;"), "heat": fmt("heat", "&deg;"),
        "chill": fmt("chill", "&deg;"), "rh": fmt("rh", "%"), "vis": fmt("vis", " mi."),
        "ceil": msg["ceil"].title() if type(msg["ceil"]) == str else fmt("ceil", " ft."),
        "wbgt": fmt("wbgt", "&deg;"), "p": f'{round(msg["p"], 2)} in.' if msg["p"] else None
    })

    # Get wind description 
    wind, wdir, wspeed, wgust = ["Wind:"], msg["wdir"], msg["wspeed"], msg["wgust"]

    c_dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]

    # Convert wdir to cardinal direction if necessary
    if type(wdir) == str: wind.append(wdir)
    elif type(wdir) == float and wdir < 360:
        if wdir < 0: wdir += 360
        wind.append(c_dirs[round(wdir / (360 / len(c_dirs))) % len(c_dirs)])

    # Format wspeed
    if wspeed == 999: wspeed = None
    if type(wspeed) == float: wind.append(str(round(wspeed * 1.150779)))

    # Determine if wgust should be added to wind (specific to knots) and format
    if wspeed and wgust and wgust >= 18 and (wgust - wspeed >= 10):
        wind.append(f"<br>Gusts to {round(wspeed * 1.150779)}")

    msg["wind"] = " ".join(wind) if len(wind) > 1 else None

    # Remove the superfluous data
    del msg["wspeed"], msg["wdir"], msg["wgust"]

    return msg
