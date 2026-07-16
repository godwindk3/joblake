import requests
import time
import random 
from bs4 import BeautifulSoup
import json


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

# This take a list of page that use for extract urls in each page and return a list of urls for each pages
def extract_urls_from_list_page(list_page: list) -> list:
    
    pages = []
    for p in list_page:
        pages.append(extract_urls_from_html(html=p))

    return pages


