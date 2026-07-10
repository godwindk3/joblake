import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel
import os
import json

def fetch(url):
    response = requests.get(url, timeout=10)
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

    


html = fetch("https://www.topcv.vn/tim-viec-lam-moi-nhat?company_field=1&type_keyword=1&sba=1&saturday_status=0")
# save_to_txt(html=html, filename="check.txt")
print(len(extract_urls_from_html(html=html)))