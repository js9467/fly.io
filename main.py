from flask import Flask, jsonify, send_from_directory
from bs4 import BeautifulSoup
import requests
import json
import os
from datetime import datetime
from urllib.parse import urljoin

app = Flask(__name__)
DATA_FOLDER = "data"
IMAGE_FOLDER = "static/images/boats"
os.makedirs(DATA_FOLDER, exist_ok=True)
os.makedirs(IMAGE_FOLDER, exist_ok=True)

SETTINGS_URL = "https://js9467.github.io/Brtourney/settings.json"


def normalize(name):
    return name.lower().replace(" ", "_").replace("'", "").replace("-", "_")


def fetch_settings():
    return requests.get(SETTINGS_URL).json()


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def download_image(img_url, uid):
    try:
        if not img_url:
            return "/static/images/boats/default.jpg"
        ext = img_url.split(".")[-1].split("?")[0]
        file_path = f"{IMAGE_FOLDER}/{uid}.{ext}"
        if not os.path.exists(file_path):
            resp = requests.get(img_url, timeout=10)
            if resp.status_code == 200:
                with open(file_path, 'wb') as f:
                    f.write(resp.content)
        return f"/static/images/boats/{uid}.{ext}"
    except:
        return "/static/images/boats/default.jpg"


@app.route("/")
def index():
    return "✅ Fly Scraper is running."


@app.route("/scrape/participants")
def scrape_all_participants():
    settings = fetch_settings()
    results = {}

    for key, entry in settings.items():
        url = entry.get("participants")
        if not url:
            continue

        try:
            res = requests.get(url, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            participants = []

            for div in soup.select("div.col-sm-3, div.col-md-3, div.col-lg-3"):
                a_tag = div.find("a")
                href = a_tag["href"] if a_tag else ""
                if "/anglers/" in href:
                    continue  # skip anglers

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


@app.route("/scrape/events")
def scrape_all_events():
    settings = fetch_settings()
    results = {}

    for key, entry in settings.items():
        url = entry.get("events")
        if not url:
            continue

        try:
            res = requests.get(url, timeout=15)
            soup = BeautifulSoup(res.text, "html.parser")
            events = []

            # ReelTimeApps event structure often uses .feed-list-item
            for el in soup.select(".feed-list-item, .event"):
                # timestamp
                time_tag = el.select_one(".feed-time, .time, .timestamp")
                timestamp = time_tag.text.strip() if time_tag else datetime.utcnow().isoformat()

                # boat
                boat_tag = el.select_one(".feed-boat, .boat, .title")
                boat = boat_tag.text.strip() if boat_tag else "Unknown"
                uid = normalize(boat)

                # details
                details_tag = el.select_one(".feed-description, .details, p")
                details = details_tag.text.strip() if details_tag else el.get_text(strip=True)

                # classify event type
                lower_details = details.lower()
                if "released" in lower_details:
                    event_type = "Released"
                elif "pulled hook" in lower_details:
                    event_type = "Pulled Hook"
                elif "boated" in lower_details or "headed to scales" in lower_details:
                    event_type = "Boated"
                elif "wrong species" in lower_details:
                    event_type = "Wrong Species"
                else:
                    event_type = "Other"

                # Try to parse timestamp into ISO
                try:
                    # ReelTime often uses format: '2:35 PM'
                    dt = datetime.strptime(timestamp, "%I:%M %p")
                    timestamp_iso = datetime.utcnow().replace(hour=dt.hour, minute=dt.minute, second=0, microsecond=0).isoformat()
                except:
                    timestamp_iso = datetime.utcnow().isoformat()

                events.append({
                    "timestamp": timestamp_iso,
                    "event": event_type,
                    "boat": boat,
                    "uid": uid,
                    "details": details
                })

            # save JSON
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
