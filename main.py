import os
import json
import time
import threading
import requests
from flask import Flask, jsonify, send_from_directory
from bs4 import BeautifulSoup
from datetime import datetime

app = Flask(__name__)
DATA_DIR = "/data"
SETTINGS_URL = "https://js9467.github.io/Brtourney/settings.json"
HEADERS = {"User-Agent": "Mozilla/5.0"}

os.makedirs(DATA_DIR, exist_ok=True)

def normalize(name):
    return ''.join(c for c in name.lower().replace(" ", "_") if c.isalnum() or c == "_")

def load_settings():
    try:
        res = requests.get(SETTINGS_URL, headers=HEADERS, timeout=10)
        return res.json()
    except Exception as e:
        print(f"❌ Failed to load settings.json: {e}")
        return {}

def scrape_participants(tid, url):
    try:
        print(f"🔍 Scraping participants for {tid} from {url}")
        res = requests.get(url, headers=HEADERS, timeout=15)
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
            uid = normalize(boat_name)
            img_tag = div.select_one("img")
            img_url = img_tag["src"] if img_tag else ""
            if img_url.startswith("/"):
                img_url = "https://www.reeltimeapps.com" + img_url

            boats.append({
                "boat": boat_name,
                "type": "Boat",
                "uid": uid,
                "image_path": img_url
            })

        out_path = os.path.join(DATA_DIR, f"{tid}_participants.json")
        with open(out_path, "w") as f:
            json.dump(boats, f, indent=2)
        print(f"✅ Saved {len(boats)} participants to {out_path}")
    except Exception as e:
        print(f"❌ Error scraping participants for {tid}: {e}")

def scrape_events(tid, url):
    try:
        print(f"🔍 Scraping events for {tid} from {url}")
        res = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, "html.parser")
        events = []

        for li in soup.select("li.event"):
            ts_tag = li.select_one("p.pull-right")
            boat_tag = li.select_one("h4.montserrat")
            detail_tag = li.select_one("p > strong")

            if not (ts_tag and boat_tag and detail_tag):
                continue

            raw_time = ts_tag.get_text(strip=True)
            boat = boat_tag.get_text(strip=True)
            details = detail_tag.get_text(strip=True)

            try:
                ts = datetime.strptime(raw_time, "%I:%M %p").replace(year=2025, month=6, day=14)
            except:
                continue

            event_type = "Boated" if "boated" in details.lower() else (
                "Released" if "released" in details.lower() else "Other")

            events.append({
                "timestamp": ts.isoformat(),
                "event": event_type,
                "boat": boat,
                "uid": normalize(boat),
                "details": details
            })

        out_path = os.path.join(DATA_DIR, f"{tid}_events.json")
        with open(out_path, "w") as f:
            json.dump(events, f, indent=2)
        print(f"✅ Saved {len(events)} events to {out_path}")
    except Exception as e:
        print(f"❌ Error scraping events for {tid}: {e}")

def scrape_all():
    settings = load_settings()
    for name, val in settings.items():
        if not isinstance(val, dict):
            continue
        tid = normalize(name)
        if "participants" in val and val["participants"]:
            scrape_participants(tid, val["participants"])
        if "events" in val and val["events"]:
            scrape_events(tid, val["events"])

@app.route("/scrape/participants")
def manual_participants():
    settings = load_settings()
    for name, val in settings.items():
        tid = normalize(name)
        if "participants" in val and val["participants"]:
            scrape_participants(tid, val["participants"])
    return jsonify({"status": "Participants scraped"})

@app.route("/scrape/events")
def manual_events():
    settings = load_settings()
    for name, val in settings.items():
        tid = normalize(name)
        if "events" in val and val["events"]:
            scrape_events(tid, val["events"])
    return jsonify({"status": "Events scraped"})

@app.route("/data/<filename>")
def get_data(filename):
    return send_from_directory(DATA_DIR, filename)

def run_schedulers():
    def event_loop():
        while True:
            print("⏱ Scheduled event scrape...")
            settings = load_settings()
            for name, val in settings.items():
                tid = normalize(name)
                if "events" in val and val["events"]:
                    scrape_events(tid, val["events"])
            time.sleep(90)

    def participant_loop():
        while True:
            print("⏱ Scheduled participant scrape...")
            settings = load_settings()
            for name, val in settings.items():
                tid = normalize(name)
                if "participants" in val and val["participants"]:
                    scrape_participants(tid, val["participants"])
            time.sleep(21600)  # 6 hours

    threading.Thread(target=event_loop, daemon=True).start()
    threading.Thread(target=participant_loop, daemon=True).start()

if __name__ == "__main__":
    print("🚀 Boot scrape...")
    scrape_all()
    run_schedulers()
    app.run(host="0.0.0.0", port=8080)
