from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    results = soup.select(".job-tags")
    # print(type(soup.select(".job-tags")))
    for result in results:
        clean_text = result.get_text(separator= " ", strip=True)
        print(clean_text)

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"]
        )

    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    
    # page = browser.new_page()

    page = context.new_page()


    page.goto("https://www.topcv.vn/viec-lam/data-scientist/2147404.html?ta_source=JobSearchList_LinkDetail&u_sr_id=KbcA7ex7ZBBeeJSgvIcfgFgjLcHRrsxz9XW816Es_1782268004")


    html = page.content()

    parse(html)

    browser.close()






# soup = BeautifulSoup(html, "html.parser")
# print(soup.select_one(".job-detail__info--section-content-value"))
# print(page.title())
