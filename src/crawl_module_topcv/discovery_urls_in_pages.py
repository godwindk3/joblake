import requests
import time
import random 
from bs4 import BeautifulSoup
import json
import logging
from typing import Any
from collections.abc import Iterable

logger = logging.getLogger(__name__)


def extract_urls_from_item_list(
    main_entity: dict[str, Any],
) -> list[str]:
    urls: list[str] = []

    elements = main_entity.get("itemListElement", [])

    if not isinstance(elements, list):
        return urls
    
    for element in elements:
        if not isinstance(element, dict):
            continue

        direct_url = element.get("url")
        if isinstance(direct_url, str):
            urls.append(direct_url)
            continue

        nested_item = element.get("item")

        if isinstance(nested_item, dict):
            nested_url = nested_item.get("url")

            if isinstance(nested_url, str):
                urls.append(nested_url)
    return urls

        
        

def extract_urls_from_json_ld_item(
    item: dict[str, Any],
) -> list[str]:
    
    urls: list[str] = []

    main_entity = item.get("mainEntity")

    if (
        isinstance(main_entity, dict)
        and main_entity.get("@type") == "ItemList"
    ):
        urls.extend(
            extract_urls_from_item_list(main_entity)
        )
    
    direct_url = item.get("url")

    if isinstance(direct_url, str):
        urls.append(direct_url)
    
    return urls

def extract_urls_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    extracted_urls: list[str] = []

    json_ld_tags = soup.find_all(
        "script",
        type="application/ld+json",
    )

    for tag_index, tag in enumerate(json_ld_tags):
        raw_json = tag.get_text(strip=True)

        if not raw_json:
            continue

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Failed to decode JSON-LD tag %d: %s",
                tag_index,
                exc,
            )
            continue

        if isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            items = data
        else:
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            extracted_urls.extend(
                extract_urls_from_json_ld_item(item)
            )
    
    return list(dict.fromkeys(extracted_urls))


def extract_urls_from_html_pages(
    html_pages: Iterable[str],
) -> list[str]:
    urls: list[str] = []

    for html in html_pages:
        urls.extend(extract_urls_from_html(html))

    return list(dict.fromkeys(urls))
    

    


