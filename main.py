import os
import json
import time
import threading
from flask import Flask, jsonify, send_from_directory
import requests
from bs4 import BeautifulSoup
from datetime import datetime

app = Flask(__name__)
DATA_DIR = "/data"
SETTINGS_URL = "https://js9467.github.io/Brtourney/settings.json"

def normalize(name):
    return ''.join(c for c in name.lower().replace(" ", "_") if c.isalnum() or c == "_")

def load_settings():
    try:
        res = requests.get(SETTINGS_URL, timeout=10)
        return res.json()
    except Exception as e:
        print(f"❌ Failed to load settings: {e}")
        return {}

def scrape_participants(uid, url):
    try:
        res = requests.get(url, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        boats = []

        for div in soup.select("div.row > div.col-md-4"):
            name_tag = div.select_one("h4")
            if not name_tag:
                continue
            name = name_tag.get_text(strip=True)
            if not name or name.lower() in ["angler", "junior angler"]:
                continue

            boat_name = name
            boat_type = "Boat"
            uid = normalize(boat_name)

            img = div.select_one("img")
            img_url = img["src"] if img else None
            if img_url and img_url.startswith("/"):
                img_url = "https://www.reeltimeapps.com" + img_url

            boats.append({
                "boat": boat_name,
                "type": boat_type,
                "uid": uid,
                "image_path": img_url or ""
            })

        out_path = os.path.join(DATA_DIR, f"{uid}_participants.json")
        with open(out_path, "w") as f:
            json.dump(boats, f, indent=2)
        print(f"✅ {len(boats)} participants saved to {out_path}")
        return boats
    except Exception as e:
        print(f"❌ Error scraping participants: {e}")
        return []

def scrape_events(uid, url):
    try:
        res = requests.get(url, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        events = []

        for item in soup.select("li.event"):
            ts_tag = item.select_one("p.pull-right")
            boat_tag = item.select_one("h4.montserrat")
            details_tag = item.select_one("p > strong")

            if not (ts_tag and boat_tag and details_tag):
                continue

            raw_ts = ts_tag.get_text(strip=True)
            boat = boat_tag.get_text(strip=True)
            details = details_tag.get_text(strip=True)

            ts = datetime.strptime(raw_ts, "%I:%M %p").replace(year=2025, month=6, day=14)
            event_type = "Boated" if "boated" in details.lower() else (
                         "Released" if "released" in details.lower() else "Other")

            events.append({
                "timestamp": ts.isoformat(),
                "event": event_type,
                "boat": boat,
                "uid": normalize(boat),
                "details": details
            })

        out_path = os.path.join(DATA_DIR, f"{uid}_events.json")
        with open(out_path, "w") as f:
            json.dump(events, f, indent=2)
        print(f"✅ {len(events)} events saved to {out_path}")
        return events
    except Exception as e:
        print(f"❌ Error scraping events: {e}")
        return []

@app.route("/scrape/participants")
def manual_participants():
    settings = load_settings()
    for name, val in settings.items():
        if not isinstance(val, dict):
            continue
        uid = normalize(name)
        if "participants" in val and val["participants"]:
            scrape_participants(uid, val["participants"])
    return jsonify({"status": "participants scraped"})

@app.route("/scrape/events")
def manual_events():
    settings = load_settings()
    for name, val in settings.items():
        if not isinstance(val, dict):
            continue
        uid = normalize(name)
        if "events" in val and val["events"]:
            scrape_events(uid, val["events"])
    return jsonify({"status": "events scraped"})

@app.route("/data/<filename>")
def serve_data(filename):
    return send_from_directory(DATA_DIR, filename)

def schedule_participants():
    while True:
        print("⏱ Scraping participants (every 6 hours)...")
        settings = load_settings()
        for name, val in settings.items():
            if not isinstance(val, dict):
                continue
            uid = normalize(name)
            if "participants" in val and val["participants"]:
                scrape_participants(uid, val["participants"])
        time.sleep(21600)  # 6 hours

def schedule_events():
    while True:
        print("🔁 Scraping events (every 90 seconds)...")
        settings = load_settings()
        for name, val in settings.items():
            if not isinstance(val, dict):
                continue
            uid = normalize(name)
            if "events" in val and val["events"]:
                scrape_events(uid, val["events"])
        time.sleep(90)

if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    print("🚀 Starting Fly scraper...")

    # Kick off both jobs in parallel
    threading.Thread(target=schedule_participants, daemon=True).start()
    threading.Thread(target=schedule_events, daemon=True).start()

    # Run initial scrape once
    settings = load_settings()
    for name, val in settings.items():
        if not isinstance(val, dict):
            continue
        uid = normalize(name)
        if "participants" in val and val["participants"]:
            scrape_participants(uid, val["participants"])
        if "events" in val and val["events"]:
            scrape_events(uid, val["events"])

    app.run(host="0.0.0.0", port=8080)
