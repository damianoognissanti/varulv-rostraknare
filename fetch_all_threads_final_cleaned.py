import os
import requests
from bs4 import BeautifulSoup
import time
import re

BASE_URL = "https://www.rollspel.nu"
FORUM_URL = f"{BASE_URL}/forums/varulvsspel.81/"
OUTPUT_DIR = "data"
HEADERS = {"User-Agent": "VarulvScraperBot/1.0 (kontakt@example.com)"}
MAX_PAGES_PER_THREAD = 50
DELAY_BETWEEN_REQUESTS = 2  # seconds

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

def get_thread_links():
    print("🔍 Startar insamling av trådar...")
    links = []
    seen_thread_urls = set()
    page = 1
    previous_urls = set()

    while True:
        url = f"{FORUM_URL}page-{page}" if page > 1 else FORUM_URL
        print(f"📄 Hämtar forum-sida {page}: {url}")
        res = requests.get(url, headers=HEADERS)
        if res.status_code != 200:
            print(f"❌ Kunde inte hämta forumsidan (status {res.status_code}). Avbryter.")
            break
        soup = BeautifulSoup(res.text, "html.parser")
        thread_links = soup.select("div.structItem-title a[href*='/threads/']")
        if not thread_links:
            print("⚠️ Inga fler trådar hittades. Avslutar länkinsamling.")
            break

        current_urls = set()
        for link in thread_links:
            href = link["href"]
            title = link.text.strip()
            if href.startswith("/threads/") and "." in href:
                full_url = BASE_URL + href
                current_urls.add(full_url)
                if full_url not in seen_thread_urls:
                    links.append((title, full_url))
                    seen_thread_urls.add(full_url)
                    print(f"   ➕ Tråd: {title} ({full_url})")

        if current_urls == previous_urls:
            print("✅ Ingen förändring jämfört med föregående sida – antas vara sista sidan.")
            break
        previous_urls = current_urls

        page += 1
        time.sleep(DELAY_BETWEEN_REQUESTS)
    return links

def download_thread_pages(title, url):
    print(f"⬇️  Hämtar tråd: {title}")
    match = re.search(r"/threads/(.+?\.\d+)", url)
    if not match:
        print(f"❌ Kunde inte extrahera ID från: {url}")
        return
    slug_id = match.group(1)
    thread_dir = os.path.join(OUTPUT_DIR, slug_id)
    os.makedirs(thread_dir, exist_ok=True)

    last_cleaned_hash = None

    for page in range(1, MAX_PAGES_PER_THREAD + 1):
        page_url = url if page == 1 else f"{url}page-{page}"
        page_path = os.path.join(thread_dir, f"page{page}.html")
        if os.path.exists(page_path):
            print(f"   ⏩ Sida {page} finns redan, hoppar över.")
            continue
        print(f"   📥 Sida {page}: {page_url}")
        res = requests.get(page_url, headers=HEADERS)
        if res.status_code != 200:
            print(f"   ❌ Kunde inte hämta sida {page} (status {res.status_code}). Stoppar.")
            break

        cleaned = clean_html(res.text)
        current_hash = hash(cleaned)
        if current_hash == last_cleaned_hash:
            print("   ✅ Samma innehåll (efter rensning) som föregående sida – antas vara sista.")
            break
        last_cleaned_hash = current_hash

        with open(page_path, "w", encoding="utf-8") as f:
            f.write(res.text)
        print(f"   ✔ Sparade sida {page} till {page_path}")
        time.sleep(DELAY_BETWEEN_REQUESTS)

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    links = get_thread_links()
    print(f"✅ Hittade totalt {len(links)} trådar.")
    for idx, (title, url) in enumerate(links, start=1):
        print(f"➡️ Tråd {idx} av {len(links)}")
        download_thread_pages(title, url)

if __name__ == "__main__":
    main()
