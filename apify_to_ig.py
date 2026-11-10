"""
Reads the next TikTok URL from queue.txt, posts it to Instagram as a Reel,
then removes it from the queue. Uses yt-dlp + a GitHub Release for hosting
-- no paid API involved.
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


def read_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]


def write_queue(urls):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        for url in urls:
            f.write(url + "\n")


def get_video_info(video_url):
    result = subprocess.run(
        ["yt-dlp", "-J", video_url],
        capture_output=True, text=True, timeout=60,
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
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed to download video: {result.stderr[:500]}")
    if not os.path.exists(VIDEO_FILE):
        raise RuntimeError("Download reported success but video file is missing.")


def upload_to_github_release(video_id):
    owner_repo = GITHUB_REPOSITORY
    tag = f"tiktok-{video_id}-{int(time.time())}"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}

    resp = requests.post(
