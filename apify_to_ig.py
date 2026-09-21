"""
Fully automatic TikTok -> Instagram pipeline, powered by Apify (which
handles TikTok access via residential proxy, avoiding the datacenter-IP
block we hit with direct scraping).

Each run:
    1. Asks Apify for the account's recent videos + engagement stats
    2. Filters out anything already posted (tracked in posted_log.txt)
    3. Picks the single highest-engagement remaining video
    4. Posts it directly to Instagram (using Apify's video URL --
       no download/re-hosting needed)
    5. Logs it as posted

Requires these environment variables:
    APIFY_API_TOKEN   - your Apify API token
    IG_USER_ID          - your Instagram Business Account's numeric ID
    IG_ACCESS_TOKEN      - your long-lived Instagram access token
"""

import json
import os
import time

import requests

# ---- Configuration -------------------------------------------------------

TIKTOK_USERNAMES = ["funny_dogs001"]  # add more usernames here later if wanted
MAX_ITEMS_PER_ACCOUNT = 20
POSTED_LOG_FILE = "posted_log.txt"

APIFY_API_TOKEN = os.environ["APIFY_API_TOKEN"]
APIFY_ACTOR_ID = "z6GDWcyb4ZVT10ogS"

IG_USER_ID = os.environ["IG_USER_ID"]
IG_ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]
GRAPH_API_BASE = "https://graph.instagram.com"


# ---- Posted-video tracking ----------------------------------------------------


def load_posted_ids():
    if os.path.exists(POSTED_LOG_FILE):
        with open(POSTED_LOG_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def mark_as_posted(video_id):
    with open(POSTED_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(video_id + "\n")


# ---- Apify (finds + ranks candidate videos) ---------------------------------


def engagement_score(video):
    likes = video.get("likeCount") or 0
    comments = video.get("commentCount") or 0
    shares = video.get("shareCount") or 0
    saves = video.get("collectCount") or 0
    # Weight saves and shares higher -- stronger signals than a passive like.
    return likes + (comments * 2) + (shares * 3) + (saves * 3)


def fetch_candidates():
    url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/run-sync-get-dataset-items"
    payload = {
        "usernames": TIKTOK_USERNAMES,
        "maxItems": MAX_ITEMS_PER_ACCOUNT,
    }
    resp = requests.post(url, params={"token": APIFY_API_TOKEN}, json=payload, timeout=180)
    resp.raise_for_status()
    return resp.json()


def pick_best_candidate():
    posted_ids = load_posted_ids()
    videos = fetch_candidates()

    candidates = [v for v in videos if v.get("id") not in posted_ids and v.get("videoUrl")]
    if not candidates:
        return None

    candidates.sort(key=engagement_score, reverse=True)
    return candidates[0]


# ---- Instagram Content Publishing API ----------------------------------------


def publish_to_instagram(video_url, caption):
    resp = requests.post(
        f"{GRAPH_API_BASE}/{IG_USER_ID}/media",
        data={
            "video_url": video_url,
            "caption": caption,
            "media_type": "REELS",
            "like_and_view_counts_disabled": "true",  # hides like/view counts
            "access_token": IG_ACCESS_TOKEN,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Instagram media creation failed ({resp.status_code}): {resp.text}")
    resp.raise_for_status()
    creation_id = resp.json()["id"]

    for attempt in range(20):
        time.sleep(10)
        resp = requests.get(
            f"{GRAPH_API_BASE}/{creation_id}",
            params={"fields": "status_code", "access_token": IG_ACCESS_TOKEN},
            timeout=30,
        )
        resp.raise_for_status()
        status = resp.json().get("status_code")
        print(f"Instagram processing status: {status} (check {attempt + 1}/20)")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError("Instagram reported an error processing the video.")
    else:
        raise RuntimeError("Timed out waiting for Instagram to process the video.")

    resp = requests.post(
        f"{GRAPH_API_BASE}/{IG_USER_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": IG_ACCESS_TOKEN},
        timeout=30,
    )
    if not resp.ok:
        print(f"Instagram publish failed ({resp.status_code}): {resp.text}")
    resp.raise_for_status()
    return resp.json()


def post_to_story(video_url):
    """Also share the same video to the account's Story."""
    resp = requests.post(
        f"{GRAPH_API_BASE}/{IG_USER_ID}/media",
        data={
            "video_url": video_url,
            "media_type": "STORIES",
            "access_token": IG_ACCESS_TOKEN,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Story media creation failed ({resp.status_code}): {resp.text}")
        return None
    creation_id = resp.json()["id"]

    for attempt in range(20):
        time.sleep(10)
        resp = requests.get(
            f"{GRAPH_API_BASE}/{creation_id}",
            params={"fields": "status_code", "access_token": IG_ACCESS_TOKEN},
            timeout=30,
        )
        resp.raise_for_status()
        status = resp.json().get("status_code")
        print(f"Story processing status: {status} (check {attempt + 1}/20)")
        if status == "FINISHED":
            break
        if status == "ERROR":
            print("Instagram reported an error processing the story -- skipping story post.")
            return None
    else:
        print("Timed out waiting for story processing -- skipping story post.")
        return None

    resp = requests.post(
        f"{GRAPH_API_BASE}/{IG_USER_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": IG_ACCESS_TOKEN},
        timeout=30,
    )
    if not resp.ok:
        print(f"Story publish failed ({resp.status_code}): {resp.text}")
        return None
    return resp.json()


# ---- Main -------------------------------------------------------------------


def main():
    print("Fetching candidates from Apify...")
    best = pick_best_candidate()

    if best is None:
        print("No new unposted candidates found.")
        return

    video_id = best["id"]
    video_url = best["videoUrl"]
    caption = (best.get("description") or "")[:2200]
    score = engagement_score(best)

    print(f"Best candidate: {video_id} (score={score}, likes={best.get('likeCount')}, "
          f"comments={best.get('commentCount')}, shares={best.get('shareCount')}, "
          f"saves={best.get('collectCount')})")

    print("Publishing to Instagram...")
    result = publish_to_instagram(video_url, caption)
    print(f"Published: {result}")

    print("Also posting to Story...")
    duration_seconds = (best.get("durationMS") or 0) / 1000
    if duration_seconds > 58:
        print(f"Skipping story post -- video is {duration_seconds:.0f}s, longer than Instagram's ~60s Story limit.")
    else:
        story_result = post_to_story(video_url)
        if story_result:
            print(f"Story posted: {story_result}")

    mark_as_posted(video_id)
    print("Marked as posted.")


if __name__ == "__main__":
    main()
