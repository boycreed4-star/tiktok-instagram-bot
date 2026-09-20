"""
Posts a SPECIFIC TikTok video (that you provide the link to) to Instagram
as a Reel. Triggered manually each time via GitHub Actions' "Run workflow"
button, rather than auto-detecting new videos.

Requires these environment variables:
    IG_USER_ID       - your Instagram Business Account's numeric ID
    IG_ACCESS_TOKEN   - a long-lived access token with content-publish permission
    GITHUB_TOKEN       - provided automatically by GitHub Actions
    GITHUB_REPOSITORY  - provided automatically by GitHub Actions
    TIKTOK_URL          - the specific TikTok video link to repost (you provide
                          this when running the workflow)
"""

import json
import os
import subprocess
import time

import requests

VIDEO_FILE = "latest_video.mp4"

IG_USER_ID = os.environ["IG_USER_ID"]
IG_ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPOSITORY = os.environ["GITHUB_REPOSITORY"]
TIKTOK_URL = os.environ["TIKTOK_URL"]

GRAPH_API_BASE = "https://graph.instagram.com"


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
    return {
        "id": data.get("id"),
        "title": data.get("title", ""),
    }


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
    print(f"Fetching info for: {TIKTOK_URL}")
    video_info = get_video_info(TIKTOK_URL)
    video_id = video_info["id"]

    print(f"Downloading video {video_id}...")
    download_video(TIKTOK_URL)

    print("Uploading to GitHub Release for public hosting...")
    public_video_url = upload_to_github_release(video_id)
    print(f"Hosted at: {public_video_url}")

    caption = video_info.get("title", "")
    print("Publishing to Instagram...")
    result = publish_to_instagram(public_video_url, caption)
    print(f"Published: {result}")


if __name__ == "__main__":
    main()
