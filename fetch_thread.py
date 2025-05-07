import os
import requests
import re
import time
from bs4 import BeautifulSoup
from datetime import datetime

HEADERS = {"User-Agent": "VarulvScraperBot/1.0 (kontakt@example.com)"}
MAX_PAGES = 50
DELAY = 1  # seconds

def clean_html(text):
    lines = text.splitlines()
    filtered = []
    patterns = [
        re.compile(r'data-csrf=".*?"'),
        re.compile(r'name="_xfToken" value=".*?"'),
        re.compile(r"csrf: '.*?'"),
        re.compile(r"now: \d+")
    ]
    for line in lines:
        for pattern in patterns:
            line = pattern.sub('', line)
        filtered.append(line)
    return ' '.join(filtered)

def download_thread(base_url):
    match = re.search(r"/threads/(.+?\.\d+)", base_url)
    if not match:
        print(f"❌ Ogiltig URL: {base_url}")
        return

    thread_id = match.group(1)
    folder = os.path.join("data", thread_id)
    os.makedirs(folder, exist_ok=True)

    print(f"📥 Hämtar tråd: {thread_id}")

    last_hash = None
    for page in range(1, MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}/page-{page}"
        filepath = os.path.join(folder, f"page{page}.html")

        print(f"   🌐 Sida {page}: {url}")
        res = requests.get(url, headers=HEADERS)
        if res.status_code != 200:
            print("   🛑 Stopp: HTTP-fel.")
            break

        cleaned = clean_html(res.text)
        current_hash = hash(cleaned)

        if current_hash == last_hash:
            print("   ✅ Inget nytt innehåll. Avslutar.")
            break
        last_hash = current_hash

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(res.text)
        print(f"   ✔ Sparade sida {page}")
        time.sleep(DELAY)

    # Skapa uppdateringsstämpel
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(folder, "updated.txt"), "w", encoding="utf-8") as f:
        f.write(now)
    print(f"📌 Uppdateringsinfo sparad: {now}")

if __name__ == "__main__":
    THREAD_URL = os.getenv("THREAD_URL")
    if not THREAD_URL:
        print("⚠️ Miljövariabel THREAD_URL saknas.")
        exit(1)
    download_thread(THREAD_URL)
