import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel
import os
import json
import re
import time
import random   
from playwright.sync_api import sync_playwright

def slice_html_regex(html_content: str) -> str:
    # Pattern explanation:
    # <script : Matches exactly "<script "
    # [^>]* : Matches any characters except ">" (handles random attributes like id or class)
    # type=   : Matches exactly "type="
    # ["\']   : Matches either a single quote or double quote
    # application/ld\+json : Matches the exact mimetype (escaping the + sign)
    pattern = r'<script[^>]*type=["\']application/ld\+json["\']'
    
    # Search for the pattern in the html string (ignoring case)
    match = re.search(pattern, html_content, re.IGNORECASE)
    
    if match:
        # match.start() gives the exact index where the '<script' begins
        # Slice from this index to the end of the document
        return html_content[match.start():]
    
    # Return empty if the tag is completely missing
    return ""

def check_size(html_content : str) -> None:
    size_in_bytes = len(html_content.encode('utf-8'))

    # Convert to KB and MB for easier reading
    size_in_kb = size_in_bytes / 1024
    size_in_mb = size_in_kb / 1024

    print(f"File size: {size_in_bytes} Bytes")
    print(f"File size: {size_in_kb:.2f} KB")
    print(f"File size: {size_in_mb:.2f} MB")

    # Check threshold before saving (e.g., only save if < 5MB)
    if size_in_mb > 5:
        print("Warning: HTML file is too large to save completely.")

def fetch(base_url: str, payload: dict) -> str:
    response = requests.get(base_url, params=payload, timeout=10)
    response.raise_for_status
    return response.text


def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    print(soup.select_one(".imy-5.paragraph").text)

def print_html(html: str) -> None:
    print(html)

def save_to_txt(html: str, filename: str) -> bool:
    """
    Save html to txt to check
    """
    try:
        with open(filename, "w", encoding="utf-8") as file:
            file.write(html)
        print("Done")
        return True
    except Exception as e:
        print("Error!!")
        return False
    
def extract_urls_from_html(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    extracted_urls = []
    # Find all <script type = "applocation/ld+json"> tags
    json_ld_tags = soup.find_all('script', type='application/ld+json')
    
    for tag in json_ld_tags:
        try:
            data = json.loads(tag.string)
            if isinstance(data, dict):
                items = [data]
            elif isinstance(data, list):
                items = data
            else:
                continue
            
            for item in items:
                if item.get("mainEntity").get('@type') == 'ItemList' and 'itemListElement' in item['mainEntity']:
                    
                    for element in item['mainEntity']['itemListElement']:
                        if isinstance(element, dict) and 'url' in element:
                            extracted_urls.append(element['url'])
                        elif isinstance(element, dict) and 'item' in element and isinstance(element['item'], dict):     # Can only use this
                            if 'url' in element['item']:
                                extracted_urls.append(element['item']['url'])
                elif 'url' in item:
                    extracted_urls.append(item['url'])
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            continue

    return list(dict.fromkeys(extracted_urls))

def extract_urls_from_list_page(list_page: list) -> list:
    
    pages = []
    for p in list_page:
        pages.append(extract_urls_from_html(html=p))

    return pages

def fetch_all_it_jobs_page(base_url: str, page_number: int = 5) -> list:

    htmls = []

    for i in range(1, page_number):
        payload = {
            "type_keyword": 1,
            "category_family": "r257",
            "saturday_status": 0,
            "page": i,
        }

        page_html = fetch(base_url=base_url, payload=payload)
        htmls.append(page_html)
        print(f"Finish page {i}")

        sleep_time = random.uniform(4.0, 6)

        print(f"Waiting: {sleep_time:.2f} seconds....")

        time.sleep(sleep_time)

        
    return htmls

def extract_html_from_single_url(url: str) -> str:
    print(url)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            )
        
        try:
            context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = context.new_page()
            page.goto(url)

            if page.content():
                print(f"Finish {url}")
                export_file_by_url(page.content())
            else:
                print(f"Error at {url}")

            return page.content()

        finally:
            browser.close()

def extract_html_from_a_page(page: list) -> list:
    html_page = []

    for url in page:

        html_page.append(extract_html_from_single_url(url=url))

        sleep_time = random.uniform(4.0, 6)
        print(f"Waiting: {sleep_time:.2f} seconds")

        time.sleep(sleep_time)

    return html_page

def extract_html_from_a_list_page(list_page: list) -> list:
    html_list_page = []
    index = 1

    for page in list_page:
        print(page)
        print(f"Start page {index}")
        html_list_page.append(extract_html_from_a_page(page=page))
        index += 1
    
    return html_list_page

def export_file(data: list) -> None:
    with open("result_test.txt", "w", encoding="utf-8") as f:
        for item in data:
            f.write(item + "\n")

def export_file_by_url(data: str) -> None:
    with open("result_test.txt", "w", encoding="utf-8") as f:
        f.write(data + "\n")
        f.write("\n" + "="*80 + "\n\n")
    

# html = fetch("https://www.topcv.vn/tim-viec-lam-moi-nhat?company_field=1&type_keyword=1&page=3&saturday_status=0&sba=1")
# # save_to_txt(html=html, filename="check.txt")
# html = slice_html_regex(html_content=html)

# result = extract_urls_from_html(html=html)
# print(result)
# print(len(result))
# Encode string to UTF-8 to calculate the exact byte size
url = "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257?type_keyword=1&page=2&category_family=r257&saturday_status=0"
base_url = "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257"
list_page = fetch_all_it_jobs_page(base_url=base_url, page_number=2)
# print(len(result))
# print(result[-1])
page = extract_urls_from_html(list_page[-1])
print(page)
print(len(page))
htmls = extract_html_from_a_page(page)





