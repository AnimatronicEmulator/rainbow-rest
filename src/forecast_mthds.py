from datetime import datetime as dt, timedelta as tdelta, timezone as tz
from math import cos
from re import findall, finditer, search
from requests import get

from src.helpers import ICON_HI, STATIONS, URLS, wx_calcs

# Retrive and format NBM bulletin data 
def get_nbm(lat, lon, product):
    # Returns NBM bulletin data for product for the nearest station

    elems = ["SKY", "WSP", "GST", "WDR", "TMP", "DPT", "VIS", "CIG", "PZR", "PSN", "PPL", "PRA"]

    match product:
        case "nbe":
            h_iter, h_row, elems = 12, 2, elems + ["T12"]
            
            get_sdate = lambda b, d: dt.strptime(" ".join([
                str((d + tdelta(days=1)).year), str((d + tdelta(days=1)).month),
                list(filter(None, findall(r"\d*", b[1].split("|")[0])))[0],
                list(filter(None, findall(r"\d*", b[2].split("|")[0])))[0]
            ]), "%Y %m %d %H").replace(tzinfo=tz.utc)

        case "nbs":
            h_iter, h_row, elems = 3, 3, elems + ["T03"]
            
            get_sdate = lambda b, d: dt.strptime(" ".join([
                str((d + tdelta(hours=6)).year),
                search(r"[A-Z]{3}", search(r"(?<=\/)[A-Z]*\s*\d*", b[1]).group(0)).group(0),
                list(filter(None, findall(r"\d*", search(r"(?<=\/)[A-Z]*\s*\d*", b[1]).group(0))))[0],
                list(filter(None, findall(r"\d*", b[2])))[0]
            ]), "%Y %b %d %H").replace(tzinfo=tz.utc)

        case "nbh": 
            h_iter, h_row, elems = 1, 1, elems + ["T01"]
            get_sdate = lambda b, d: d + tdelta(hours=1)

    # Get nearest station
    deltas = [sum(x) for x in zip(
        [(abs(lon - STATIONS[s]["LON"]) * cos(lat)) ** 2 for s in STATIONS],
        [abs(lat - STATIONS[s]["LAT"]) ** 2 for s in STATIONS]
    )]

    station = list(STATIONS.keys())[deltas.index(min(deltas))]

    # Find ideal bulletin
    furl = lambda d: URLS["nbm"] % {"d": d.strftime("%Y%m%d"), "h": d.strftime("%H"), "p": product}

    nbm_date = dt.utcnow() - tdelta(hours=1) if product == "nbh" else dt.utcnow()

    bulletin = get(furl(nbm_date))
    while bulletin.status_code != 200:
        nbm_date -= tdelta(hours=1)
        bulletin = get(furl(nbm_date))

    # Get station bulletin for product + 1st datetime; Return error if any fail
    try:
        bulletin = bulletin.text
        b = bulletin[bulletin.index(station):]
        b = b[:b.index(search(r"\n\s{10}", b).group(0))].split("\n")
        hr0 = get_sdate(b, nbm_date)
    except (ValueError, AttributeError): return "nbm_text", station

    # Eliminate CLIMO column if it exists (usually in nbe)
    if "CLIMO" in b[1]: b = [x[:b[1].index("CLIMO")] for x in b]

    # The values are organized into cols separated by the end-indexes of each hour
    idxs = [0] + [h.end(0) for h in finditer(r"\d*", b[h_row]) if h.group(0)]

    # Limit bulletin rows to those with relevant elements
    b = [r for r in b if search(r"\w{3}", r).group(0) in elems]

    # Reorganize bulletin as a dict keyed by elems with lists of their hour-values
    b = {search(r"\w{3}", row).group(0): [float(v[0]) if v else None for v in [
        list(filter(None, findall(r"\d*", row[idxs[i]:idxs[i + 1]])))
        for i in range(len(idxs) - 1)]] for row in b}
    
    # Modify "CIG" and "VIS" values if necessary 
    # cig measured in 100s miles, -88 if unlimited, vis in 1/10 miles
    if "CIG" in b: b["CIG"] = ["Unlimited" if v == -88 else v for v in b["CIG"]]
    if "CIG" in b: b["CIG"] = [v * 100 if type(v) == float else v for v in b["CIG"]]
    if "VIS" in b: b["VIS"] = [v / 10 if type(v) == float else v for v in b["VIS"]]

    # Organize data into a dict keyed by hour with dicts of element values
    data = {hr0 + tdelta(hours=(i * h_iter)): {k: v[i] for k, v in b.items()} 
            for i in range(len(idxs) - 1)}

    return data, station

# Parse NBM bulletin data by the hour 
def parse_nbm(data, is_current=False):
    # Returns data from the hour in current-endpoint format
    msg = {"wspeed": "WSP", "wgust": "GST", "wdir": "WDR", "t": "TMP", "dew": "DPT", "vis": "VIS", "ceil": "CIG"}
    sky = {"skc": 0, "few": 12.5, "sct": 37.5, "bkn": 62.5, "ovc": 87.5}
    sprc, prc = {"hi": 60, "showers": 60}, {
        "wind": "WSP", "rain": "PRA", "snow": "PSN", "fzra": "PZR", 
        "sleet": "PPL", "tsra": "T01", "tsra": "T03", "tsra": "T12"
    }

    # Limit data to conditions that exist and aren't NBM null (i.e., -99)
    data = {k: v for k, v in data.items() if v not in (None, -99)}

    # Get WSP in mph, TMP, and DPT if they exist
    wsp = data["WSP"] * 1.15077945 if "WSP" in data else None
    tmp = data["TMP"] if "TMP" in data else None
    dpt = data["DPT"] if "DPT" in data else None

    # Get calc values heat, chill, rh and add hot or cold to conds if necessary
    conds, calcs = [], wx_calcs(tmp, wsp, dpt=dpt)
    if calcs["chill"] or (tmp and tmp <= 0): conds.append("cold")
    if calcs["heat"]: conds.append("hot")

    qual = 90 if is_current else 20

    # Add remaining relevant wx conditions
    conds += [k for k, v in prc.items() if v in data and data[v] >= qual]
    conds += [k for k, v in sky.items() if "SKY" in data and data["SKY"] >= v]
    conds += [k for k, v in sprc.items() if "SKY" in data and data["SKY"] <= v]
    conds = [e for e in ICON_HI if all([x in conds for x in e.split("_")])]

    # Find the maximum hierarchical condition (default skc)
    max_cond = max(conds, key=lambda x: ICON_HI[x]) if conds else "skc"

    # Generate return data
    msg = {k: data[v] if v in data else None for k, v in msg.items()}
    msg.update({"rh": calcs["rh"], "name": max_cond})

    return msg    
