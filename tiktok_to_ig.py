"""
Pulls the latest public video from a TikTok profile and posts it to
Instagram as a Reel, using:
    - yt-dlp (downloads the TikTok video, no API key needed)
    - a GitHub Release (to host the video at a public URL, since
      Instagram's API needs a URL, not a direct file upload)
    - Instagram's official Content Publishing API (Graph API)

Requires these environment variables:
    IG_USER_ID       - your Instagram Business Account's numeric ID
    IG_ACCESS_TOKEN   - a long-lived access token with content-publish permission
    GITHUB_TOKEN       - provided automatically by GitHub Actions, used to
                         create the release that hosts the video file
    GITHUB_REPOSITORY  - provided automatically by GitHub Actions (owner/repo)

This is genuinely experimental -- neither TikTok's page structure nor the
exact Instagram API response shapes have been tested against live data.
Expect a debugging round the first time this actually runs.
"""

import json
import os
import subprocess
import time

import requests

# ---- Configuration -------------------------------------------------------

TIKTOK_USERNAME = "warmpets520"
STATE_FILE = "tiktok_last_video.txt"
VIDEO_FILE = "latest_video.mp4"

IG_USER_ID = os.environ["IG_USER_ID"]
IG_ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPOSITORY = os.environ["GITHUB_REPOSITORY"]  # e.g. "owner/repo"

GRAPH_API_BASE = "https://graph.instagram.com"  # Instagram Login path -- no Facebook Page needed


# ---- State ------------------------------------------------------------------


def get_last_video_id():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return f.read().strip() or None
    return None


def save_last_video_id(video_id):
    with open(STATE_FILE, "w") as f:
        f.write(video_id)


# ---- TikTok (via yt-dlp) ----------------------------------------------------


def get_latest_video_info():
    """Get metadata for the most recent video without downloading it yet."""
    result = subprocess.run(
        [
            "yt-dlp",
            "--flat-playlist",
            "--playlist-items", "1",
            "-J",
            f"https://www.tiktok.com/@{TIKTOK_USERNAME}",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed to list videos: {result.stderr[:500]}")

    data = json.loads(result.stdout)
    entries = data.get("entries", [])
    if not entries:
        raise RuntimeError("No videos found on this TikTok profile.")

    entry = entries[0]
    return {
        "id": entry.get("id"),
        "url": entry.get("url") or f"https://www.tiktok.com/@{TIKTOK_USERNAME}/video/{entry.get('id')}",
        "title": entry.get("title", ""),
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

    # Create the release
    resp = requests.post(
        f"https://api.github.com/repos/{owner_repo}/releases",
        headers=headers,
        json={"tag_name": tag, "name": tag, "draft": False, "prerelease": False},
        timeout=30,
    )
    resp.raise_for_status()
    release = resp.json()
    upload_url = release["upload_url"].split("{")[0]  # strip the templated part

    # Upload the video file as a release asset
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
    # Step 1: create a media container
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

    # Step 2: wait for Instagram to finish processing the video
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

    # Step 3: publish it
    resp = requests.post(
        f"{GRAPH_API_BASE}/{IG_USER_ID}/media_publish",
        data={"creation_id": creation_id, "access_token": IG_ACCESS_TOKEN},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---- Main -------------------------------------------------------------------


def main():
    last_video_id = get_last_video_id()

    video_info = get_latest_video_info()
    video_id = video_info["id"]

    if video_id == last_video_id:
        print("No new video since last check.")
        return

    print(f"New video found: {video_id}. Downloading...")
    download_video(video_info["url"])

    print("Uploading to GitHub Release for public hosting...")
    public_video_url = upload_to_github_release(video_id)
    print(f"Hosted at: {public_video_url}")

    caption = video_info.get("title", "")
    print("Publishing to Instagram...")
    result = publish_to_instagram(public_video_url, caption)
    print(f"Published: {result}")

    save_last_video_id(video_id)


if __name__ == "__main__":
    main()
