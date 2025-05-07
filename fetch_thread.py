# fetch_thread.py
import os
import requests
import sys

def download_thread(base_url):
    thread_id = base_url.rstrip('/').split('/')[-1]
    folder = f"data/{thread_id}"
    os.makedirs(folder, exist_ok=True)

    for page in range(1, 100):  # Max 99 sidor
        url = base_url if page == 1 else f"{base_url}/page-{page}"
        print(f"Laddar: {url}")
        res = requests.get(url)
        if res.status_code != 200 or "Det finns inga fler sidor" in res.text:
            break
        with open(f"{folder}/page{page}.html", "w", encoding="utf-8") as f:
            f.write(res.text)

if __name__ == "__main__":
    THREAD_URL = os.getenv("THREAD_URL")
    if not THREAD_URL:
        print("THREAD_URL måste anges som miljövariabel.")
        sys.exit(1)
    download_thread(THREAD_URL)
