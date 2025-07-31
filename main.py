
from flask import Flask, jsonify, send_from_directory
from bs4 import BeautifulSoup
import requests
import json
import os
from datetime import datetime
from urllib.parse import urljoin

app = Flask(__name__)

# Unified volume root
VOLUME_ROOT = "/app/persist"
DATA_FOLDER = os.path.join(VOLUME_ROOT, "data")
IMAGE_FOLDER = os.path.join(VOLUME_ROOT, "images", "boats")

# Ensure all necessary folders exist
os.makedirs(DATA_FOLDER, exist_ok=True)
os.makedirs(IMAGE_FOLDER, exist_ok=True)
os.makedirs("/app/static/images", exist_ok=True)

# Symlink static/images/boats -> persistent image folder (for serving images)
if not os.path.exists("/app/static/images/boats"):
    os.symlink(IMAGE_FOLDER, "/app/static/images/boats")

SETTINGS_URL = "https://js9467.github.io/Brtourney/settings.json"


def normalize(name):
    return name.lower().replace(" ", "_").replace("'", "").replace("-", "_")


def fetch_settings():
    try:
        res = requests.get(SETTINGS_URL, timeout=10)
        res.raise_for_status()
        data = res.json()
        print(f"✅ Loaded settings: {list(data.keys())}")
        return data
    except Exception as e:
        print(f"❌ Error fetching settings: {e}")
        return {}


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def download_image(img_url, uid):
    try:
        if not img_url:
            return "/static/images/boats/default.jpg"
        ext = img_url.split(".")[-1].split("?")[0]
        file_path = os.path.join(IMAGE_FOLDER, f"{uid}.{ext}")
        if not os.path.exists(file_path):
            resp = requests.get(img_url, timeout=10)
            if resp.status_code == 200:
                with open(file_path, 'wb') as f:
                    f.write(resp.content)
        return f"/static/images/boats/{uid}.{ext}"
    except Exception as e:
        print(f"❌ Failed to download image for {uid}: {e}")
        return "/static/images/boats/default.jpg"


@app.route("/")
def index():
    return "✅ Fly Scraper is running."


@app.route("/scrape/participants")
def scrape_all_participants():
    settings = fetch_settings()
    results = {}

    for key, entry in settings.items():
        if not entry or not isinstance(entry, dict):
            results[key] = "❌ Skipped: invalid entry"
            continue

        url = entry.get("participants")
        if not url:
            results[key] = "❌ Skipped: no participants URL"
            continue

        try:
            res = requests.get(url, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            participants = []

            for div in soup.select("div.col-sm-3, div.col-md-3, div.col-lg-3"):
                a_tag = div.find("a")
                href = a_tag["href"] if a_tag else ""
                if "/anglers/" in href:
                    continue

                name_tag = div.select_one(".post-title")
                type_tag = div.select_one(".post-meta li")
                img_tag = div.find("img")

                boat_name = name_tag.text.strip() if name_tag else ""
                boat_type = type_tag.text.strip() if type_tag and type_tag.text.strip() else ""
                image_url = urljoin(url, img_tag["src"]) if img_tag and img_tag.get("src") else ""

                if not boat_name:
                    continue

                uid = normalize(boat_name)
                image_path = download_image(image_url, uid)

                participants.append({
                    "uid": uid,
                    "boat": boat_name,
                    "type": boat_type,
                    "image_path": image_path
                })

            path = os.path.join(DATA_FOLDER, f"{normalize(key)}_participants.json")
            save_json(path, {"participants": participants, "timestamp": datetime.utcnow().isoformat()})

            results[key] = f"{len(participants)} boats saved."
        except Exception as e:
            results[key] = f"❌ Failed: {str(e)}"

    return jsonify(results)


from dateutil import parser as date_parser

@app.route("/scrape/events")
def scrape_all_events():
    settings = fetch_settings()
    results = {}

    for key, entry in settings.items():
        if not entry or not isinstance(entry, dict):
            results[key] = "❌ Skipped: invalid entry"
            continue

        url = entry.get("events")
        if not url:
            results[key] = "❌ Skipped: no events URL"
            continue

        try:
            res = requests.get(url, timeout=15)
            soup = BeautifulSoup(res.text, "html.parser")
            events = []
            seen = set()

            # Load participants if available (for display name)
            participants_path = os.path.join(DATA_FOLDER, f"{normalize(key)}_participants.json")
            participants = {}
            if os.path.exists(participants_path):
                with open(participants_path) as f:
                    pdata = json.load(f)
                    participants = {p["uid"]: p for p in pdata.get("participants", [])}

            for el in soup.select("article.m-b-20, article.entry, div.activity, li.event, div.feed-item"):
                time_tag = el.select_one("p.pull-right")
                boat_tag = el.select_one("h4.montserrat")
                desc_tag = el.select_one("p > strong")

                if not time_tag or not boat_tag or not desc_tag:
                    continue

                raw_time = time_tag.get_text(strip=True).replace("@", "").strip()
                try:
                    ts = date_parser.parse(raw_time).replace(year=datetime.now().year).isoformat()
                except:
                    continue

                boat = boat_tag.get_text(strip=True)
                desc = desc_tag.get_text(strip=True)
                uid = normalize(boat)

                # Resolve boat name if in participants
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

                key_id = f"{uid}_{event_type}_{ts}"
                if key_id in seen:
                    continue
                seen.add(key_id)

                events.append({
                    "timestamp": ts,
                    "event": event_type,
                    "boat": boat,
                    "uid": uid,
                    "details": desc
                })

            events.sort(key=lambda e: e["timestamp"])
            path = os.path.join(DATA_FOLDER, f"{normalize(key)}_events.json")
            save_json(path, {"events": events, "timestamp": datetime.utcnow().isoformat()})

            results[key] = f"{len(events)} events saved."
        except Exception as e:
            results[key] = f"❌ Failed: {str(e)}"

    return jsonify(results)


@app.route("/data/<filename>")
def serve_data(filename):
    return send_from_directory(DATA_FOLDER, filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
