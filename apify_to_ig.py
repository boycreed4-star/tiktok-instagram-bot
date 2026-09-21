name: Post best TikTok video to Instagram

on:
  workflow_dispatch: {}   # triggered externally by cron-job.org at 8am/12pm/3pm/6pm/9pm

permissions:
  contents: write

jobs:
  post:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install requests

      - name: Run bot
        env:
          APIFY_API_TOKEN: ${{ secrets.APIFY_API_TOKEN }}
          IG_USER_ID: ${{ secrets.IG_USER_ID }}
          IG_ACCESS_TOKEN: ${{ secrets.IG_ACCESS_TOKEN }}
        run: python apify_to_ig.py

      - name: Save posted log
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add posted_log.txt
          git diff --staged --quiet || git commit -m "Update posted videos log"
          git push
