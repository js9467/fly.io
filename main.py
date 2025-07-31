from flask import Flask, jsonify
import os, json, time
from datetime import datetime, timedelta
from threading import Thread
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)
CACHE_DIR = "cache"
SETTINGS_URL = "https://js9467.github.io/Brtourney/settings.json"

os.makedirs(CACHE_DIR, exist_ok=True)

def normalize(name):
    return name.lower().replace(" ", "_").replace("'", "").replace("/", "_")

def load_settings():
    try:
        return requests.get(SETTINGS_URL).json()
    except:
        return {}

def get_cache_path(tournament, key):
    folder = os.path.join(CACHE_DIR, normalize(tournament))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{key}.json")

def is_fresh(path, max_age_min):
    if not os.path.exists(path): return False
    age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))
    return age < timedelta(minutes=max_age_min)

def scrape_participants(tournament, url):
    try:
        html = requests.get(url, timeout=20).text
        soup = BeautifulSoup(html, 'html.parser')
        boats = []
        seen = set()
        for article in soup.select("article.post.format-image"):
            name_tag = article.select_one("h2.post-title")
            type_tag = article.select_one("ul.post-meta li")
            if not name_tag: continue
            name = name_tag.get_text(strip=True)
            if ',' in name or name.lower() in seen: continue
            seen.add(name.lower())
            uid = normalize(name)
            boats.append({
                "uid": uid,
                "boat": name,
                "type": type_tag.get_text(strip=True) if type_tag else "",
                "image_path": f"/static/images/boats/{uid}.jpg"
            })
        path = get_cache_path(tournament, "participants")
        with open(path, "w") as f:
            json.dump(boats, f, indent=2)
        print(f"✅ Scraped {len(boats)} participants for {tournament}")
    except Exception as e:
        print(f"❌ Failed to scrape participants for {tournament}: {e}")

from dateutil import parser as date_parser

def scrape_events(tournament, force=False):
    try:
        events_file = get_cache_path(tournament, "events")
        if not force and is_fresh(events_file, 1.5):
            with open(events_file) as f:
                return json.load(f)

        print(f"📡 Scraping events for {tournament}")
        remote = requests.get(SETTINGS_URL).json()
        key = next((k for k in remote if normalize(k) == normalize(tournament)), None)
        if not key:
            print(f"⚠️ Tournament {tournament} not found in settings.json")
            return []

        events_url = remote[key].get("events")
        if not events_url:
            print(f"⚠️ No events URL for tournament {tournament}")
            return []

        html = requests.get(events_url, timeout=20).text
        soup = BeautifulSoup(html, 'html.parser')

        participants = {}
        p_path = get_cache_path(tournament, "participants")
        if os.path.exists(p_path):
            with open(p_path) as f:
                participants = {p["uid"]: p for p in json.load(f)}

        events = []
        seen = set()

        for article in soup.select("article.m-b-20, article.entry, div.activity, li.event, div.feed-item"):
            time_tag = article.select_one("p.pull-right")
            name_tag = article.select_one("h4.montserrat")
            desc_tag = article.select_one("p > strong")

            if not time_tag or not name_tag or not desc_tag:
                continue

            try:
                raw_time = time_tag.get_text(strip=True).replace("@", "")
                ts = date_parser.parse(raw_time).replace(year=datetime.now().year).isoformat()
            except:
                continue

            boat = name_tag.get_text(strip=True)
            desc = desc_tag.get_text(strip=True)
            uid = normalize(boat)

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

        print(f"✅ Saved {len(events)} events for {tournament}")
        return events

    except Exception as e:
        print(f"❌ Error scraping events for {tournament}: {e}")
        return []


def scrape_all_now():
    print("🚀 Running initial full scrape")
    settings = load_settings()
    for name, entry in settings.items():
        if not isinstance(entry, dict):
            continue  # ⚠ Skip nulls or non-dict values
        if entry.get("participants"):
            scrape_participants(name, entry["participants"])
        if entry.get("events"):
            scrape_events(name, entry["events"])
    print("✅ Initial scrape complete.")


def background_scheduler():
    scrape_all_now()
    while True:
        settings = load_settings()
        for name, entry in settings.items():
            if not isinstance(entry, dict):
                continue  # ⚠ Skip null entries
            p_path = get_cache_path(name, "participants")
            e_path = get_cache_path(name, "events")

            if entry.get("participants") and not is_fresh(p_path, 360):
                scrape_participants(name, entry["participants"])
            if entry.get("events") and not is_fresh(e_path, 1.5):
                scrape_events(name, entry["events"])
        time.sleep(30)


@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "Tournament Scraper API"})

@app.route("/api/<tournament>/participants")
def api_participants(tournament):
    path = get_cache_path(tournament, "participants")
    if not os.path.exists(path):
        return jsonify({"status": "error", "message": "No participant data"}), 404
    with open(path) as f:
        return jsonify(json.load(f))

@app.route("/api/<tournament>/events")
def api_events(tournament):
    path = get_cache_path(tournament, "events")
    if not os.path.exists(path):
        return jsonify({"status": "error", "message": "No event data"}), 404
    with open(path) as f:
        return jsonify(json.load(f))

if __name__ == "__main__":
    Thread(target=background_scheduler, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
