"""
Reads the next TikTok URL from queue.txt, posts it to Instagram as a Reel,
then removes it from the queue. Runs on a schedule -- you keep the queue
filled by editing queue.txt (one TikTok video URL per line) whenever you
want to add something.
"""

import json
import os
import subprocess
import time

import requests

QUEUE_FILE = "queue.txt"
VIDEO_FILE = "latest_video.mp4"

IG_USER_ID = os.environ["IG_USER_ID"]
IG_ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPOSITORY = os.environ["GITHUB_REPOSITORY"]

GRAPH_API_BASE = "https://graph.instagram.com"


# ---- Queue ------------------------------------------------------------------


def read_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]


def write_queue(urls):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        for url in urls:
            f.write(url + "\n")


# ---- TikTok (via yt-dlp) ----------------------------------------------------


def get_video_info(video_url):
    result = subprocess.run(
        ["yt-dlp", "-J", video_url],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed to fetch video info: {result.stderr[:500]}")

    data = json.loads(result.stdout)
    return {"id": data.get("id"), "title": data.get("title", "")}


def download_video(video_url):
    if os.path.exists(VIDEO_FILE):
        os.remove(VIDEO_FILE)

    result = subprocess.run(
        ["yt-dlp", "-f", "best", "-o", VIDEO_FILE, video_url],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed to download video: {result.stderr[:500]}")

    if not os.path.exists(VIDEO_FILE):
        raise RuntimeError("Download reported success but video file is missing.")


# ---- Hosting the video via a GitHub Release ---------------------------------


def upload_to_github_release(video_id):
    owner_repo = GITHUB_REPOSITORY
    tag = f"tiktok-{video_id}-{int(time.time())}"

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    resp = requests.post(
        f"https://api.github.com/repos/{owner_repo}/releases",
        headers=headers,
        json={"tag_name": tag, "name": tag, "draft": False, "prerelease": False},
        timeout=30,
    )
    resp.raise_for_status()
    release = resp.json()
    upload_url = release["upload_url"].split("{")[0]

    with open(VIDEO_FILE, "rb") as f:
        video_data = f.read()

    resp = requests.post(
        f"{upload_url}?name=video.mp4",
        headers={**headers, "Content-Type": "video/mp4"},
        data=video_data,
        timeout=120,
    )
    resp.raise_for_status()
    asset = resp.json()
    return asset["browser_download_url"]


# ---- Instagram Content Publishing API ----------------------------------------


def publish_to_instagram(video_url, caption):
    resp = requests.post(
        f"{GRAPH_API_BASE}/{IG_USER_ID}/media",
        data={
            "video_url": video_url,
            "caption": caption,
            "media_type": "REELS",
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


# ---- Main -------------------------------------------------------------------


def main():
    queue = read_queue()

    if not queue:
        print("Queue is empty -- nothing to post. Add a TikTok URL to queue.txt.")
        return

    next_url = queue[0]
    remaining = queue[1:]

    print(f"Processing next queued video: {next_url}")
    video_info = get_video_info(next_url)
    video_id = video_info["id"]

    print(f"Downloading video {video_id}...")
    download_video(next_url)

    print("Uploading to GitHub Release for public hosting...")
    public_video_url = upload_to_github_release(video_id)
    print(f"Hosted at: {public_video_url}")

    caption = video_info.get("title", "")
    print("Publishing to Instagram...")
    result = publish_to_instagram(public_video_url, caption)
    print(f"Published: {result}")

    write_queue(remaining)
    print(f"Removed from queue. {len(remaining)} video(s) remaining.")


if __name__ == "__main__":
    main()
