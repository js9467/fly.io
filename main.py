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
        response = requests.get(SETTINGS_URL, timeout=10)
        return response.json()
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

def scrape_all():
    settings = load_settings()
    for name, data in settings.items():
        if not isinstance(data, dict): continue
        uid = normalize(name)

        if "participants" in data and data["participants"]:
            scrape_participants(uid, data["participants"])
        if "events" in data and data["events"]:
            scrape_events(uid, data["events"])

@app.route("/scrape/participants")
def scrape_participants_route():
    scrape_all()
    return jsonify({"status": "Participants scraped"})

@app.route("/scrape/events")
def scrape_events_route():
    scrape_all()
    return jsonify({"status": "Events scraped"})

@app.route("/data/<filename>")
def serve_data(filename):
    return send_from_directory(DATA_DIR, filename)

def schedule_scrape():
    while True:
        print("⏱ Auto-scraping every 60s...")
        scrape_all()
        time.sleep(60)

@app.before_serving
async def startup():
    await scrape_participants()
    await scrape_events()

def on_start():
    print("🚀 Initial scrape on startup")
    threading.Thread(target=schedule_scrape, daemon=True).start()

if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    print("📦 Starting scraper service...")
    scrape_all()  # Optional: scrape immediately when launching
    app.run(host="0.0.0.0", port=8080)
