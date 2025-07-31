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
def scrape_participants(tournament_name, participants_url):
    try:
        html = requests.get(participants_url, timeout=20).text
        soup = BeautifulSoup(html, "html.parser")
        entries = []
        for row in soup.select(".participant-row, div.row"):
            boat_tag = row.select_one(".participant-boat, h4")
            type_tag = row.select_one(".participant-type, p")
            img_tag = row.select_one("img")

            if not boat_tag:
                continue

            boat = boat_tag.get_text(strip=True)
            type_ = type_tag.get_text(strip=True) if type_tag else ""
            uid = normalize(boat)
            image_url = img_tag["src"] if img_tag and "src" in img_tag.attrs else ""

            # Image handling
            ext = os.path.splitext(image_url)[-1] or ".jpg"
            image_path = f"{STATIC_IMAGE_PATH}/{uid}{ext}"
            local_path = f"static/images/boats/{uid}{ext}"
            os.makedirs("static/images/boats", exist_ok=True)

            if image_url and not os.path.exists(local_path):
                try:
                    img_data = requests.get(image_url, timeout=10).content
                    with open(local_path, "wb") as f:
                        f.write(img_data)
                except Exception as e:
                    print(f"⚠️ Failed to download image for {boat}: {e}")
                    image_path = f"{STATIC_IMAGE_PATH}/default.jpg"

            entries.append({
                "uid": uid,
                "boat": boat,
                "type": type_,
                "image_path": image_path
            })

        with open(get_cache_path(tournament_name, "participants"), "w") as f:
            json.dump(entries, f, indent=2)
        print(f"✅ Scraped {len(entries)} participants for {tournament_name}")
    except Exception as e:
        print(f"❌ Error scraping participants for {tournament_name}: {e}")

def scrape_events(tournament_name, event_url, participants):
    try:
        html = requests.get(event_url, timeout=20).text
        soup = BeautifulSoup(html, 'html.parser')
        new_events = []
        seen = set()

        for article in soup.select("article, div.feed-item, li.event, div.activity"):
            time_tag = article.select_one("p.pull-right")
            name_tag = article.select_one("h4, .montserrat")
            desc_tag = article.select_one("p > strong")

            if not name_tag or not desc_tag:
                continue

            raw_time = time_tag.get_text(strip=True).replace("@", "") if time_tag else ""
            try:
                timestamp = date_parser.parse(raw_time).replace(year=datetime.now().year).isoformat()
            except:
                timestamp = datetime.now().isoformat()

            boat = name_tag.get_text(strip=True)
            desc = desc_tag.get_text(strip=True)
            uid = normalize(boat)

            # Normalize from participants if match found
            if uid in participants:
                boat = participants[uid]["boat"]

            event_type = "Other"
            if "released" in desc.lower(): event_type = "Released"
            elif "boated" in desc.lower(): event_type = "Boated"
            elif "pulled hook" in desc.lower(): event_type = "Pulled Hook"
            elif "wrong species" in desc.lower(): event_type = "Wrong Species"

            key = f"{uid}_{event_type}_{timestamp}"
            if key in seen:
                continue
            seen.add(key)

            new_events.append({
                "timestamp": timestamp,
                "event": event_type,
                "boat": boat,
                "uid": uid,
                "details": desc
            })

        with open(get_cache_path(tournament_name, "events"), "w") as f:
            json.dump(new_events, f, indent=2)
        print(f"✅ Saved {len(new_events)} events for {tournament_name}")
    except Exception as e:
        print(f"❌ Error scraping events for {tournament_name}: {e}")

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
