import time
import random   
from playwright.sync_api import sync_playwright

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
                # export_file_by_url(page.content())
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

# Mainly using this function to extract all html of each url
def extract_html_from_a_list_page(list_page: list) -> list:
    html_list_page = []
    index = 1

    for page in list_page:
        print(page)
        print(f"Start page {index}")
        html_list_page.append(extract_html_from_a_page(page=page))
        index += 1
    
    return html_list_page