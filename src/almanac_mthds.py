from datetime import datetime as dt, timedelta as tdelta
from astral import LocationInfo as Loc
from astral.sun import sun
import ephem

from src.helpers import icon_wx

def get_solar(lat, lon, tz, date):
    msg, days = [], [date, date + tdelta(days=1)]

    loc = Loc("", "", "", float(lat), float(lon))
    for x in range(len(days)):
        s = sun(loc.observer, days[x], tzinfo=tz)
        msg.append({
            "wday": days[x].strftime("%A"), "tz": days[x].tzname(),
            "rise": s["sunrise"].strftime("%I:%M %p"),
            "set": s["sunset"].strftime("%I:%M %p"),
        })

    return msg

def get_lunar(lat, lon, tz, date):
    msg, data = [], sorted([
        ("New", ephem.next_new_moon(ephem.Date(date.date()))),
        ("First", ephem.next_first_quarter_moon(ephem.Date(date.date()))),
        ("Full", ephem.next_full_moon(ephem.Date(date.date()))),
        ("Last", ephem.next_last_quarter_moon(ephem.Date(date.date()))),
    ], key=lambda x: x[1])

    for x in range(len(data)):
        msg.append({
            "date": ephem.to_timezone(data[x][1], tz).strftime("%b %#d"),
            "icon": icon_wx(lat, lon, data[x][0])["icon"], "phase": data[x][0]
        })

    return msg
