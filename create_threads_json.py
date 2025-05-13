import os
import json
from bs4 import BeautifulSoup

DATA_DIR = "data"
OUTPUT_FILE = os.path.join(DATA_DIR, "threads.json")

def extract_title_cleaned(html_path):
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    title_tag = soup.find("title")
    if not title_tag or not title_tag.text:
        return None

    title = title_tag.text.strip()
    if title.startswith("Nekromanti - "):
        title = title[len("Nekromanti - "):]
    if title.startswith("Varulv - "):
        title = title[len("Varulv - "):]
    if "| rollspel.nu" in title:
        title = title.replace("| rollspel.nu", "").strip()

    return title

def count_pages(thread_path):
    return sum(
        1 for fname in os.listdir(thread_path)
        if fname.startswith("page") and fname.endswith(".html")
    )

def main():
    threads = []

    for folder_name in sorted(os.listdir(DATA_DIR)):
        thread_path = os.path.join(DATA_DIR, folder_name)
        page1_path = os.path.join(thread_path, "page1.html")

        print(f"🔍 Läser {thread_path}.")
        if os.path.isdir(thread_path) and os.path.isfile(page1_path):
            title = extract_title_cleaned(page1_path)
            if title:
                pages = count_pages(thread_path)
                threads.append({
                    "name": title,
                    "slug": folder_name,
                    "pages": pages
                })

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(threads, f, ensure_ascii=False, indent=2)

    print(f"✅ Skapade {OUTPUT_FILE} med {len(threads)} trådar.")

if __name__ == "__main__":
    main()
