import os
import requests
from dotenv import load_dotenv

load_dotenv()

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")

def check_token():
    print("Checking Token Permissions...")
    url = f"https://graph.facebook.com/debug_token?input_token={PAGE_ACCESS_TOKEN}&access_token={PAGE_ACCESS_TOKEN}"
    response = requests.get(url)
    print(response.json())

if __name__ == "__main__":
    check_token()
