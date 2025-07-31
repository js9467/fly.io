import os
import json
import requests
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, send_from_directory
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

app = Flask(__name__)

DATA_DIR = "data"
STATIC_IMAGE_PATH = "/static/images/boats"

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# === Utility Functions ===
def normalize(text):
    return text.lower().replace(" ", "_").replace("'", "").replace("\"", "")

def get_cache_path(tournament, name):
    safe_name = normalize(tournament)
    return os.path.join(DATA_DIR, f"{safe_name}_{name}.json")

def load_settings():
    r = requests.get("https://js9467.github.io/Brtourney/settings.json")
    return r.json()

# === Scraping Functions ===
import os
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime

def normalize_boat_name(name):
    return ''.join(c.lower() if c.isalnum() else '_' for c in name).strip('_')

def scrape_participants(name, url):
    print(f"📡 Scraping participants for {name} from {url}")
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"⚠️ Failed to fetch participants for {name}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        participants = []
        cards = soup.select("div.card")  # Confirm this still matches

        for card in cards:
            boat = card.select_one("h4")
            if boat:
                boat_name = boat.get_text(strip=True)
                if any(x in boat_name.lower() for x in ["angler", "junior", "lady", "mate"]):
                    continue  # Skip non-boat entries
                uid = normalize_boat_name(boat_name)
                type_ = card.select_one("div.card-text")
                participants.append({
                    "uid": uid,
                    "boat": boat_name,
                    "type": type_.get_text(strip=True) if type_ else "",
                    "image_path": f"/static/images/boats/{uid}.jpg"
                })

        print(f"✅ Scraped {len(participants)} participants for {name}")
        os.makedirs(f"data/{name}", exist_ok=True)
        with open(f"data/{name}/participants.json", "w") as f:
            json.dump(participants, f, indent=2)
        return participants

    except Exception as e:
        print(f"❌ Error scraping participants for {name}: {e}")
        return []

def scrape_events(name, url, participants):
    print(f"📡 Scraping events for {name} from {url}")
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"⚠️ Failed to fetch events for {name}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        event_blocks = soup.select("article.m-b-20")
        print(f"🔎 Found {len(event_blocks)} event containers")

        events = []
        for block in event_blocks:
            try:
                time_el = block.select_one("p.pull-right")
                title_el = block.select_one("h4.montserrat")
                details_el = block.select_one("p > strong")

                if not (time_el and title_el and details_el):
                    continue

                time_str = time_el.get_text(strip=True)
                timestamp = datetime.strptime(time_str, "%I:%M %p").replace(year=datetime.now().year).isoformat()

                details = details_el.get_text(strip=True)
                boat_name = title_el.get_text(strip=True)
                uid = normalize_boat_name(boat_name)

                events.append({
                    "timestamp": timestamp,
                    "event": title_el.get_text(strip=True),
                    "boat": boat_name,
                    "uid": uid,
                    "details": details
                })
            except Exception as e:
                print(f"⚠️ Error parsing event block: {e}")
                continue

        print(f"✅ Saved {len(events)} events for {name}")
        os.makedirs(f"data/{name}", exist_ok=True)
        with open(f"data/{name}/events.json", "w") as f:
            json.dump(events, f, indent=2)
        return events

    except Exception as e:
        print(f"❌ Error scraping events for {name}: {e}")
        return []


# === Full Scrape ===
def scrape_all_now():
    print("🚀 Running initial full scrape")
    settings = load_settings()

    for name, entry in settings.items():
        if not isinstance(entry, dict):
            print(f"⏭ Skipping invalid entry: {name}")
            continue

        participants_url = entry.get("participants")
        events_url = entry.get("events")
        if not participants_url or not events_url:
            print(f"⏭ Skipping {name} due to missing URLs")
            continue

        scrape_participants(name, participants_url)

        participants_path = get_cache_path(name, "participants")
        participants = {}
        if os.path.exists(participants_path):
            with open(participants_path) as f:
                participants = {p["uid"]: p for p in json.load(f)}

        print(f"📡 Scraping events for {name}")
        scrape_events(name, events_url, participants)

# === Background Tasks ===
def background_scheduler():
    def run():
        while True:
            try:
                settings = load_settings()
                for name, entry in settings.items():
                    if not isinstance(entry, dict):
                        continue
                    events_url = entry.get("events")
                    if not events_url:
                        continue

                    participants_path = get_cache_path(name, "participants")
                    participants = {}
                    if os.path.exists(participants_path):
                        with open(participants_path) as f:
                            participants = {p["uid"]: p for p in json.load(f)}

                    scrape_events(name, events_url, participants)
            except Exception as e:
                print(f"Scheduler error: {e}")

            time.sleep(90)  # every 90 seconds

    threading.Thread(target=run, daemon=True).start()

# === Flask Routes ===
@app.route("/api/<tournament>/participants")
def get_participants(tournament):
    path = get_cache_path(tournament, "participants")
    if os.path.exists(path):
        with open(path) as f:
            return jsonify(json.load(f))
    return jsonify([])

@app.route("/api/<tournament>/events")
def get_events(tournament):
    path = get_cache_path(tournament, "events")
    if os.path.exists(path):
        with open(path) as f:
            return jsonify(json.load(f))
    return jsonify([])

@app.route("/static/images/boats/<path:filename>")
def serve_image(filename):
    return send_from_directory("static/images/boats", filename)

if __name__ == "__main__":
    scrape_all_now()
    background_scheduler()
    app.run(host="0.0.0.0", port=8080)
