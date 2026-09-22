"""
Independently picks the highest-engagement not-yet-posted-to-Facebook video
and posts it to a Facebook Page. Uses its own separate posted log so it can
pick different videos than the Instagram bot over time.

Requires these environment variables:
    APIFY_API_TOKEN     - your Apify API token
    FB_PAGE_ID           - your Facebook Page's numeric ID
    FB_PAGE_ACCESS_TOKEN  - a long-lived Page access token
"""

import os

import requests

# ---- Configuration -------------------------------------------------------

TIKTOK_USERNAMES = ["funny_dogs001"]  # keep in sync with the Instagram bot, or set independently
MAX_ITEMS_PER_ACCOUNT = 20
POSTED_LOG_FILE = "posted_log_fb.txt"

APIFY_API_TOKEN = os.environ["APIFY_API_TOKEN"]
APIFY_ACTOR_ID = "z6GDWcyb4ZVT10ogS"

FB_PAGE_ID = os.environ["FB_PAGE_ID"]
FB_PAGE_ACCESS_TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


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
    return likes + (comments * 2) + (shares * 3) + (saves * 3)


def fetch_candidates():
    url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/run-sync-get-dataset-items"
    payload = {
        "usernames": TIKTOK_USERNAMES,
        "maxItems": MAX_ITEMS_PER_ACCOUNT,
    }
    resp = requests.post(url, params={"token": APIFY_API_TOKEN}, json=payload, timeout=180)
    if not resp.ok:
        print(f"Apify request failed ({resp.status_code}): {resp.text[:1000]}")
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


# ---- Facebook Page video posting ---------------------------------------------


def post_to_facebook(video_url, caption):
    """Posts as a Facebook Reel (not a regular video post) using Meta's
    dedicated Video Reels publishing flow."""

    # Step 1: start the upload session
    resp = requests.post(
        f"{GRAPH_API_BASE}/{FB_PAGE_ID}/video_reels",
        data={
            "upload_phase": "start",
            "access_token": FB_PAGE_ACCESS_TOKEN,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Facebook reel session start failed ({resp.status_code}): {resp.text}")
    resp.raise_for_status()
    session = resp.json()
    video_id = session["video_id"]

    # Step 2: tell Facebook to fetch the video from our hosted URL
    resp = requests.post(
        f"{GRAPH_API_BASE}/{video_id}",
        data={
            "file_url": video_url,
            "access_token": FB_PAGE_ACCESS_TOKEN,
        },
        timeout=120,
    )
    if not resp.ok:
        print(f"Facebook reel upload failed ({resp.status_code}): {resp.text}")
    resp.raise_for_status()

    # Step 3: finish and publish
    resp = requests.post(
        f"{GRAPH_API_BASE}/{FB_PAGE_ID}/video_reels",
        data={
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": caption,
            "access_token": FB_PAGE_ACCESS_TOKEN,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Facebook reel publish failed ({resp.status_code}): {resp.text}")
    resp.raise_for_status()
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

    print("Publishing to Facebook...")
    result = post_to_facebook(video_url, caption)
    print(f"Published: {result}")

    mark_as_posted(video_id)
    print("Marked as posted.")


if __name__ == "__main__":
    main()
