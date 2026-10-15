#!/usr/bin/env python3
"""Převede rozpis zápasů ze sipky.org na iCalendar (.ics) soubor.

Použití:
    python sipky_to_ics.py --out public/lany.ics
    python sipky_to_ics.py --input ulozena_stranka.html --out lany.ics   # test bez sítě
"""
import argparse
import re
import sys
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- NASTAVENÍ
# Při nové sezóně stačí změnit odkaz (season=, league=, team=).
URL = ("https://www.sipky.org/?region=pak&page=rozpis-utkani&league_type=611"
       "&season=6243&league=119616&team=153600&round=")
OUR_TEAM = "Šipkaři Lány"
CAL_NAME = "Šipkaři Lány – liga"
MATCH_HOURS = 3                       # délka události v kalendáři
DEFAULT_TIME = (18, 0)                # když by chyběl čas zápasu
BASE = "https://www.sipky.org/"
# -------------------------------------------------------------------------

DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")


def clean(s):
    return " ".join(s.split())


def fetch(url):
    import requests
    r = requests.get(url, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (compatible; lany-kalendar/1.0)",
        "Accept-Language": "cs",
    })
    r.raise_for_status()
    return r.content, (r.encoding or "windows-1250")


def parse(html, encoding="windows-1250"):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser", from_encoding=encoding) \
        if isinstance(html, bytes) else BeautifulSoup(html, "html.parser")
    matches = []
    for tr in soup.find_all("tr"):
        if tr.find("tr"):          # přeskoč řádky obalující jiné tabulky
            continue
        links = tr.find_all("a", href=True)
        teams = [a for a in links if "page=profil-druzstva" in a["href"]]
        if len(teams) != 2:
            continue
        dm = DATE_RE.search(tr.get_text(" ", strip=True))
        if not dm:
            continue
        d, m, y = map(int, dm.groups())

        # čas je v následujícím řádku (pod datem)
        hh, mm = DEFAULT_TIME
        nxt = tr.find_next_sibling("tr")
        if nxt:
            tm = TIME_RE.search(nxt.get_text(" ", strip=True))
            if tm:
                hh, mm = int(tm.group(1)), int(tm.group(2))

        home, away = clean(teams[0].get_text()), clean(teams[1].get_text())
        if OUR_TEAM not in (home, away):
            continue

        place_a = next((a for a in links if "page=hraci-misto" in a["href"]), None)
        place = clean(place_a.get_text()) if place_a else ""

        mid = None
        for a in links:
            mm_ = re.search(r"league_match=(\d+)", a["href"])
            if mm_:
                mid = mm_.group(1)
                break
        rnd = ""
        for a in links:
            if "round=" in a["href"]:
                rnd = clean(a.get_text()).rstrip(".")
                break

        score = None
        td = teams[0].find_parent("td")
        if td:
            sib = [clean(t.get_text()) for t in td.find_next_siblings("td")[:3]]
            if len(sib) == 3 and sib[0].isdigit() and sib[2].isdigit():
                score = (int(sib[0]), int(sib[2]))

        matches.append(dict(
            id=mid or f"{y}{m:02d}{d:02d}-{home}-{away}",
            start=datetime(y, m, d, hh, mm),
            home=home, away=away, is_home=(home == OUR_TEAM),
            place=place, round=rnd, score=score,
            url=(BASE + f"?region=pak&page=detail-zapisu-ligoveho-utkani&league_match={mid}")
            if mid else URL,
        ))
    matches.sort(key=lambda x: x["start"])
    return matches


# ------------------------------------------------------------------ ICS
def esc(s):
    return (s.replace("\\", "\\\\").replace(";", "\\;")
             .replace(",", "\\,").replace("\n", "\\n"))


def fold(line):
    """Řádky v ICS se zalamují po 75 bajtech."""
    raw, out = line.encode("utf-8"), []
    while len(raw) > 75:
        cut = 75
        while (raw[cut] & 0xC0) == 0x80:     # nerozdělit UTF-8 znak
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    out.append(raw.decode("utf-8"))
    return "\r\n".join(out)


VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/Prague
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE""".split("\n")


def build_ics(matches):
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    L = ["BEGIN:VCALENDAR", "VERSION:2.0",
         "PRODID:-//lany-kalendar//sipky.org//CS", "CALSCALE:GREGORIAN",
         "METHOD:PUBLISH", f"X-WR-CALNAME:{esc(CAL_NAME)}",
         "X-WR-TIMEZONE:Europe/Prague",
         "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    L += VTIMEZONE
    for m in matches:
        end = m["start"] + timedelta(hours=MATCH_HOURS)
        opp = m["away"] if m["is_home"] else m["home"]
        title = (f"🏠 DOMA – {opp}" if m["is_home"] else f"🚗 VENKU – {opp}")
        desc = [f"{m['home']} vs {m['away']}"]
        if m["round"]:
            desc.insert(0, f"{m['round']}. kolo")
        desc.append("Hrajeme doma" if m["is_home"] else "Hrajeme venku")
        if m["score"]:
            desc.append(f"Výsledek: {m['score'][0]}:{m['score'][1]}")
        desc.append(m["url"])
        L += ["BEGIN:VEVENT",
              f"UID:zapas-{m['id']}@sipky.org",
              f"DTSTAMP:{now}",
              f"DTSTART;TZID=Europe/Prague:{m['start']:%Y%m%dT%H%M%S}",
              f"DTEND;TZID=Europe/Prague:{end:%Y%m%dT%H%M%S}",
              f"SUMMARY:{esc(title)}",
              f"LOCATION:{esc(m['place'])}" if m["place"] else "X-NOLOC:1",
              f"DESCRIPTION:{esc(chr(10).join(desc))}",
              f"URL:{m['url']}",
              "END:VEVENT"]
    L.append("END:VCALENDAR")
    L = [x for x in L if x != "X-NOLOC:1"]
    return "\r\n".join(fold(x) for x in L) + "\r\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="lany.ics")
    ap.add_argument("--input", help="místo stahování načti uložené HTML")
    a = ap.parse_args()

    if a.input:
        with open(a.input, "rb") as f:
            html, enc = f.read(), "utf-8"
    else:
        html, enc = fetch(URL)
    matches = parse(html, enc)
    if not matches:
        # Nepřepisujeme fungující kalendář prázdným – job raději selže.
        sys.exit("CHYBA: na stránce nebyl nalezen žádný zápas (změnila se struktura?).")
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        f.write(build_ics(matches))
    print(f"OK: {len(matches)} zápasů -> {a.out}")


if __name__ == "__main__":
    main()
