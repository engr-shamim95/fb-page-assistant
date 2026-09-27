import os
import requests
from dotenv import load_dotenv

load_dotenv()

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")

def check_subscriptions():
    print("Checking Page Subscriptions...")
    url = f"https://graph.facebook.com/v20.0/me/subscribed_apps?access_token={PAGE_ACCESS_TOKEN}"
    response = requests.get(url)
    print(response.status_code)
    print(response.json())

if __name__ == "__main__":
    check_subscriptions()
