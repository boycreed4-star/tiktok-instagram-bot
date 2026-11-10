"""
Reads the next TikTok URL from queue.txt, posts it to Instagram as a Reel,
then removes it from the queue. Uses yt-dlp + a GitHub Release for hosting.
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
        lines = [line.strip() for line in f]
    return [x for x in lines if x and not x.startswith("#")]


def write_queue(urls):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        for url in urls:
            f.write(url + "\n")


def run_cmd(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def get_video_info(video_url):
    result = run_cmd(["yt-dlp", "-J", video_url], 60)
    if result.returncode != 0:
        raise RuntimeError("yt-dlp failed to fetch video info: " + result.stderr[:500])
    data = json.loads(result.stdout)
    return {"id": data.get("id"), "title": data.get("title", "")}


def download_video(video_url):
    if os.path.exists(VIDEO_FILE):
        os.remove(VIDEO_FILE)
    result = run_cmd(["yt-dlp", "-f", "best", "-o", VIDEO_FILE, video_url], 180)
    if result.returncode != 0:
        raise RuntimeError("yt-dlp failed to download video: " + result.stderr[:500])
    if not os.path.exists(VIDEO_FILE):
        raise RuntimeError("Download reported success but video file is missing.")


def upload_to_github_release(video_id):
    tag = "tiktok-" + str(video_id) + "-" + str(int(time.time()))
    headers = {"Authorization": "Bearer " + GITHUB_TOKEN, "Accept": "application/vnd.github+json"}
    body = {"tag_name": tag, "name": tag, "draft": False, "prerelease": False}
    api = "https://api.github.com/repos/" + GITHUB_REPOSITORY + "/releases"
    resp = requests.post(api, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    upload_url = resp.json()["upload_url"].split("{")[0]

    with open(VIDEO_FILE, "rb") as f:
        video_data = f.read()

    up_headers = dict(headers)
    up_headers["Content-Type"] = "video/mp4"
    resp = requests.post(upload_url + "?name=video.mp4", headers=up_headers, data=video_data, timeout=120)
    resp.raise_for_status()
    return resp.json()["browser_download_url"]


def publish_to_instagram(video_url, caption):
    media_url = GRAPH_API_BASE + "/" + IG_USER_ID + "/media"
    payload = {"video_url": video_url, "caption": caption, "media_type": "REELS", "access_token": IG_ACCESS_TOKEN}
    resp = requests.post(media_url, data=payload, timeout=30)
    if not resp.ok:
        print("Instagram media creation failed (" + str(resp.status_code) + "): " + resp.text)
    resp.raise_for_status()
    creation_id = resp.json()["id"]

    for attempt in range(20):
        time.sleep(10)
        status_url = GRAPH_API_BASE + "/" + creation_id
        params = {"fields": "status_code", "access_token": IG_ACCESS_TOKEN}
        resp = requests.get(status_url, params=params, timeout=30)
        resp.raise_for_status()
        status = resp.json().get("status_code")
        print("Instagram processing status: " + str(status) + " (check " + str(attempt + 1) + "/20)")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError("Instagram reported an error processing the video.")
    else:
        raise RuntimeError("Timed out waiting for Instagram to process the video.")

    publish_url = GRAPH_API_BASE + "/" + IG_USER_ID + "/media_publish"
    data = {"creation_id": creation_id, "access_token": IG_ACCESS_TOKEN}
    resp = requests.post(publish_url, data=data, timeout=30)
    if not resp.ok:
        print("Instagram publish failed (" + str(resp.status_code) + "): " + resp.text)
    resp.raise_for_status()
    return resp.json()


def main():
    queue = read_queue()

    if not queue:
        print("Queue is empty -- nothing to post. Add a TikTok URL to queue.txt.")
        return

    next_url = queue[0]
    remaining = queue[1:]

    print("Processing next queued video: " + next_url)
    video_info = get_video_info(next_url)
    video_id = video_info["id"]

    print("Downloading video " + str(video_id) + "...")
    download_video(next_url)

    print("Uploading to GitHub Release for public hosting...")
    public_video_url = upload_to_github_release(video_id)
    print("Hosted at: " + public_video_url)

    caption = video_info.get("title", "")
    print("Publishing to Instagram...")
    result = publish_to_instagram(public_video_url, caption)
    print("Published: " + str(result))

    write_queue(remaining)
    print("Removed from queue. " + str(len(remaining)) + " video(s) remaining.")


if __name__ == "__main__":
    main()
