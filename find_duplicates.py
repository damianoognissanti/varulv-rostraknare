import os
import re
from bs4 import BeautifulSoup

def extract_title(html):
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    return title_tag.text.strip() if title_tag else None

def verify_titles(base_dir="data"):
    print("Verifierar att filnamn och <title> matchar sidnummer...")

    errors = []

    for thread_folder in os.listdir(base_dir):
        thread_path = os.path.join(base_dir, thread_folder)
        if not os.path.isdir(thread_path):
            continue

        for filename in sorted(os.listdir(thread_path)):
            match = re.match(r"page(\d+)\.html", filename)
            if not match:
                continue

            page_num = int(match.group(1))
            full_path = os.path.join(thread_path, filename)

            with open(full_path, "r", encoding="utf-8") as f:
                html = f.read()
                title = extract_title(html)
                if not title:
                    errors.append((full_path, "Saknar <title>"))
                    continue

                # Kontroll: har eller saknar | Page N
                expected = f"| Page {page_num} |" if page_num > 1 else None
                has_page_segment = re.search(r'\|\s*Page\s+\d+\s*\|', title)
                if page_num == 1 and has_page_segment:
                    errors.append((full_path, f"page1.html har 'Page N' i titeln: {title}"))
                elif page_num > 1:
                    if not expected in title:
                        errors.append((full_path, f"Förväntade '{expected}' i titel: {title}"))

    if errors:
        print("\nFel hittades:")
        for path, msg in errors:
            print(f"   {msg}")
            print(f" {path}")
    else:
        print("\nAlla sidor har korrekta titlar.")

if __name__ == "__main__":
    verify_titles()

