from flask import Flask, jsonify
from bs4 import BeautifulSoup
from datetime import datetime
from dateutil import parser as date_parser
import os
import json
import requests

app = Flask(__name__)

PERSIST_DIR = "/app/persist"
CACHE_DIR = os.path.join(PERSIST_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def normalize_boat_name(name):
    return name.lower().replace(" ", "_").replace("’", "").replace("'", "").replace("&", "and")

def get_cache_path(tournament, filename):
    folder = os.path.join(CACHE_DIR, normalize_boat_name(tournament))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, filename)

def load_cache():
    path = os.path.join(CACHE_DIR, "cache_meta.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

def save_cache(data):
    path = os.path.join(CACHE_DIR, "cache_meta.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def is_cache_fresh(cache, key, minutes=2):
    ts = cache.get(key, {}).get("last_scraped")
    if not ts:
        return False
    last = date_parser.parse(ts)
    return (datetime.now() - last).total_seconds() < minutes * 60

def load_settings():
    try:
        return requests.get("https://js9467.github.io/Brtourney/settings.json").json()
    except:
        return {}

def fetch_page_html(url, selector):
    res = requests.get(url, timeout=20)
    if not res.ok:
        raise Exception("❌ Failed to fetch events page")
    return res.text

def scrape_participants(tournament):
    out = {}
    try:
        settings = load_settings()
        key = next((k for k in settings if normalize_boat_name(k) == normalize_boat_name(tournament)), None)
        if not key:
            return out
        url = settings[key]["participants"]
        html = requests.get(url).text
        soup = BeautifulSoup(html, "html.parser")

        for div in soup.select("div.participant-card"):
            name = div.select_one("h4")
            typ = div.select_one("p.text-xs")
            if not name:
                continue
            boat = name.text.strip()
            ptype = typ.text.strip() if typ else ""
            if ptype.lower() not in ["boat", ""]:
                continue
            uid = normalize_boat_name(boat)
            out[uid] = {
                "uid": uid,
                "boat": boat,
                "type": ptype,
                "image_path": f"/static/images/boats/{uid}.jpg"
            }

        path = get_cache_path(tournament, "participants.json")
        with open(path, "w") as f:
            json.dump(list(out.values()), f, indent=2)
    except Exception as e:
        print(f"❌ Failed to scrape participants: {e}")
    return out

def scrape_events(force=False, tournament=None):
    cache = load_cache()
    settings = load_settings()
    results = {}

    for tourney_name, info in settings.items():
        if not isinstance(info, dict) or not info.get("events"):
            results[tourney_name] = "❌ Skipped: invalid entry"
            continue

        normalized = normalize_boat_name(tourney_name)
        if tournament and normalize_boat_name(tournament) != normalized:
            continue

        cache_key = f"events_{normalized}"
        events_file = get_cache_path(tourney_name, "events.json")
        if not force and is_cache_fresh(cache, cache_key, 2):
            results[tourney_name] = f"✅ Cache fresh"
            continue

        try:
            html = fetch_page_html(info["events"], "article")
            soup = BeautifulSoup(html, "html.parser")
            participants_file = get_cache_path(tourney_name, "participants.json")
            participants = {}
            if os.path.exists(participants_file):
                with open(participants_file) as f:
                    participants = {p["uid"]: p for p in json.load(f)}

            events = []
            seen = set()
            for article in soup.select("article.m-b-20, article.entry, div.activity, li.event, div.feed-item"):
                time_tag = article.select_one("p.pull-right")
                name_tag = article.select_one("h4.montserrat")
                desc_tag = article.select_one("p > strong")
                if not time_tag or not name_tag or not desc_tag:
                    continue

                raw = time_tag.get_text(strip=True).replace("@", "").strip()
                try:
                    ts = date_parser.parse(raw).replace(year=datetime.now().year).isoformat()
                except:
                    continue

                boat = name_tag.get_text(strip=True)
                desc = desc_tag.get_text(strip=True)
                uid = normalize_boat_name(boat)

                if uid in participants:
                    boat = participants[uid]["boat"]

                if "released" in desc.lower():
                    event_type = "Released"
                elif "boated" in desc.lower():
                    event_type = "Boated"
                elif "pulled hook" in desc.lower():
                    event_type = "Pulled Hook"
                elif "wrong species" in desc.lower():
                    event_type = "Wrong Species"
                else:
                    event_type = "Other"

                key = f"{uid}_{event_type}_{ts}"
                if key in seen:
                    continue
                seen.add(key)

                events.append({
                    "timestamp": ts,
                    "event": event_type,
                    "boat": boat,
                    "uid": uid,
                    "details": desc
                })

            events.sort(key=lambda e: e["timestamp"])
            with open(events_file, "w") as f:
                json.dump(events, f, indent=2)

            cache[cache_key] = {"last_scraped": datetime.now().isoformat()}
            results[tourney_name] = f"{len(events)} events saved."

        except Exception as e:
            print(f"❌ Error scraping {tourney_name}: {e}")
            results[tourney_name] = "❌ Failed"

    save_cache(cache)
    return results

@app.route("/scrape/participants")
def route_participants():
    settings = load_settings()
    output = {}
    for tournament in settings:
        if not isinstance(settings[tournament], dict):
            continue
        out = scrape_participants(tournament)
        output[tournament] = f"{len(out)} participants saved."
    return jsonify(output)

@app.route("/scrape/events")
def route_events():
    out = scrape_events(force=True)
    return jsonify(out)

@app.route("/")
def index():
    return "✅ Tournament Scraper Running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
