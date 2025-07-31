import os
import json
import re
import time
import requests
from datetime import datetime
from threading import Thread
from flask import Flask, jsonify
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# Helper Functions

def normalize_boat_name(name):
    return re.sub(r'\W+', '_', name.lower()).strip('_')

def get_cache_path(tournament, name):
    os.makedirs(f"cache/{tournament}", exist_ok=True)
    return f"cache/{tournament}/{name}"

def fetch_page_html(url, selector):
    try:
        print(f"🌐 Fetching: {url}")
        res = requests.get(url, timeout=20)
        if res.status_code == 200:
            return res.text
    except Exception as e:
        print(f"⚠️ Error fetching {url}: {e}")
    return ""

def fetch_with_scraperapi(url):
    try:
        print(f"🔒 Fetching via ScraperAPI: {url}")
        res = requests.get(url, timeout=30)
        if res.status_code == 200:
            return res.text
    except Exception as e:
        print(f"⚠️ Error using ScraperAPI: {e}")
    return ""

def cache_boat_image(boat_name, image_url):
    uid = normalize_boat_name(boat_name)
    folder = "static/images/boats"
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{uid}.jpg")
    try:
        r = requests.get(image_url, timeout=10)
        if r.status_code == 200:
            with open(path, "wb") as f:
                f.write(r.content)
            return f"/static/images/boats/{uid}.jpg"
    except:
        pass
    return "/static/images/boats/default.jpg"

def get_current_tournament():
    return os.environ.get("TOURNAMENT", "Big Rock")

def get_all_tournaments():
    try:
        data = requests.get("https://js9467.github.io/Brtourney/settings.json").json()
        return [k for k in data if isinstance(data[k], dict) and "events" in data[k]]
    except:
        return []

# Scraper Functions (unchanged)
def scrape_participants(force=False):
    cache = load_cache()
    tournament = get_current_tournament()
    participants_file = get_cache_path(tournament, "participants.json")

    if not force and is_cache_fresh(cache, f"{tournament}_participants", 1440):
        print("✅ Participant cache is fresh — skipping scrape.")
        if os.path.exists(participants_file):
            with open(participants_file, "r") as f:
                return json.load(f)
        return []

    try:
        settings_url = "https://js9467.github.io/Brtourney/settings.json"
        settings = requests.get(settings_url, timeout=30).json()
        matching_key = next((k for k in settings if k.lower() == tournament.lower()), None)
        if not matching_key:
            raise Exception(f"Tournament '{tournament}' not found in settings.json")

        participants_url = settings[matching_key].get("participants")
        if not participants_url:
            raise Exception(f"No participants URL found for {matching_key}")

        print(f"📡 Scraping participants from: {participants_url}")

        existing_participants = {}
        if os.path.exists(participants_file):
            with open(participants_file, "r") as f:
                for p in json.load(f):
                    existing_participants[p["uid"]] = p

        html = fetch_with_scraperapi(participants_url)
        if not html:
            raise Exception("No HTML returned from ScraperAPI")

        with open("debug_participants.html", "w", encoding="utf-8") as f:
            f.write(html)

        soup = BeautifulSoup(html, 'html.parser')
        updated_participants = {}
        seen_boats = set()
        download_tasks = []

        for article in soup.select("article.post.format-image"):
            name_tag = article.select_one("h2.post-title")
            type_tag = article.select_one("ul.post-meta li")
            img_tag = article.select_one("img")

            if not name_tag:
                continue

            boat_name = name_tag.get_text(strip=True)
            if ',' in boat_name or boat_name.lower() in seen_boats:
                continue

            boat_type = type_tag.get_text(strip=True) if type_tag else ""
            uid = normalize_boat_name(boat_name)
            seen_boats.add(boat_name.lower())

            image_url = img_tag['src'] if img_tag and 'src' in img_tag.attrs else None
            image_path = existing_participants.get(uid, {}).get("image_path", "")
            local_path = image_path[1:] if image_path.startswith('/') else image_path

            force_download = (
                uid not in existing_participants or
                not image_path or
                not os.path.exists(local_path)
            )

            if force_download:
                if image_url:
                    download_tasks.append((uid, boat_name, image_url))
                    image_path = ""
                else:
                    image_path = "/static/images/boats/default.jpg"

            updated_participants[uid] = {
                "uid": uid,
                "boat": boat_name,
                "type": boat_type,
                "image_path": image_path
            }

        if download_tasks:
            print(f"📸 Downloading {len(download_tasks)} new boat images...")
            with ThreadPoolExecutor(max_workers=6) as executor:
                futures = {
                    executor.submit(cache_boat_image, bname, url): uid
                    for uid, bname, url in download_tasks
                }
                for future in futures:
                    uid = futures[future]
                    try:
                        result_path = future.result()
                        updated_participants[uid]["image_path"] = result_path
                    except Exception as e:
                        print(f"❌ Error downloading image for {uid}: {e}")
                        updated_participants[uid]["image_path"] = "/static/images/boats/default.jpg"

        updated_list = list(updated_participants.values())
        if updated_list != list(existing_participants.values()):
            with open(participants_file, "w") as f:
                json.dump(updated_list, f, indent=2)
            print(f"✅ Updated and saved {len(updated_list)} participants")
        else:
            print(f"✅ No changes detected — {len(updated_list)} participants up-to-date")

        cache[f"{tournament}_participants"] = {"last_scraped": datetime.now().isoformat()}
        save_cache(cache)
        return updated_list

    except Exception as e:
        print(f"⚠️ Error scraping participants: {e}")
        return []


def scrape_events(force=False, tournament=None):
    cache = load_cache()
    settings = load_settings()
    tournament = tournament or get_current_tournament()
    events_file = get_cache_path(tournament, "events.json")

    if not force and is_cache_fresh(cache, f"events_{tournament}", 2):
        if os.path.exists(events_file):
            with open(events_file) as f:
                return json.load(f)
        return []

    try:
        settings_url = "https://js9467.github.io/Brtourney/settings.json"
        remote = requests.get(settings_url).json()
        key = next((k for k in remote if normalize_boat_name(k) == normalize_boat_name(tournament)), None)
        events_url = remote[key]["events"]

        html = fetch_page_html(events_url, "article.m-b-20, article.entry, div.activity, li.event, div.feed-item")
        soup = BeautifulSoup(html, 'html.parser')
        events = []
        seen = set()

        participants_file = get_cache_path(tournament, "participants.json")
        participants = {}
        if os.path.exists(participants_file):
            with open(participants_file) as f:
                participants = {p["uid"]: p for p in json.load(f)}

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

            # Use participant boat name if found
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

            # Deduplication check
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

        cache[f"events_{tournament}"] = {"last_scraped": datetime.now().isoformat()}
        save_cache(cache)
        return events

    except Exception as e:
        print(f"❌ Error in scrape_events: {e}")
        return []


@app.route("/api/<tournament>/participants")
def api_participants(tournament):
    try:
        with open(get_cache_path(tournament, "participants.json")) as f:
            return jsonify(json.load(f))
    except:
        return jsonify([])

@app.route("/api/<tournament>/events")
def api_events(tournament):
    try:
        with open(get_cache_path(tournament, "events.json")) as f:
            return jsonify(json.load(f))
    except:
        return jsonify([])

def scrape_all_now():
    print("🚀 Running initial full scrape")
    for t in get_all_tournaments():
        print(f"📡 Scraping participants for {t}")
        scrape_participants(force=True)
        print(f"📡 Scraping events for {t}")
        scrape_events(force=True, tournament=t)

def background_scheduler():
    def event_loop():
        while True:
            for t in get_all_tournaments():
                scrape_events(force=True, tournament=t)
            time.sleep(90)

    def participant_loop():
        while True:
            for t in get_all_tournaments():
                scrape_participants(force=True)
            time.sleep(21600)

    Thread(target=event_loop, daemon=True).start()
    Thread(target=participant_loop, daemon=True).start()

if __name__ == "__main__":
    scrape_all_now()
    background_scheduler()
    app.run(host="0.0.0.0", port=8080)
