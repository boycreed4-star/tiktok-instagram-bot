"""
One-off script: exchanges your Instagram authorization code for a
short-lived token, then immediately exchanges that for a long-lived
(60-day) token. Run this once locally -- not part of the ongoing bot.
"""

import requests

APP_ID = "1813154586803391"
APP_SECRET = "bbb821a4a6ee481db745f58b9d9f35b1"
REDIRECT_URI = "https://localhost/"
AUTH_CODE = "AQIEvN8cSIPLecWSsWPNqiT4muMGkkJTHE7eaxPUUNyhmEZrYLAC3hAtSUxHA2fVM379mt94NS7B7KP5viRsgDgt3dygX4j6UU-Iw6xeZdhsQTb84qlp5az_oFwPHWqHeDbivrZO50iFxNWGTcJKdzS4DeZs5L0zx33dHx44Rpx0E4NQ_DucrYNKd39WeUfsKKu8dyX9PwVCFl-wc9hrT_VdMZJ_aJcptT9RDbOqc8FLJQ"

# Step 1: exchange the code for a short-lived token
resp = requests.post(
    "https://api.instagram.com/oauth/access_token",
    data={
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code": AUTH_CODE,
    },
)
print("Short-lived token response:", resp.status_code, resp.text)
resp.raise_for_status()
short_lived_token = resp.json()["access_token"]
user_id = resp.json().get("user_id")
print(f"\nYour Instagram User ID: {user_id}")

# Step 2: exchange for a long-lived (60-day) token
resp2 = requests.get(
    "https://graph.instagram.com/access_token",
    params={
        "grant_type": "ig_exchange_token",
        "client_secret": APP_SECRET,
        "access_token": short_lived_token,
    },
)
print("\nLong-lived token response:", resp2.status_code, resp2.text)
resp2.raise_for_status()
long_lived_token = resp2.json()["access_token"]

print("\n" + "=" * 60)
print("SAVE THESE TWO VALUES:")
print(f"IG_USER_ID: {user_id}")
print(f"IG_ACCESS_TOKEN: {long_lived_token}")
print("=" * 60)
