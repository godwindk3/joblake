from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

def parse(html : str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    infor_section = soup.select(".job-detail__info--sections")
    # for e in infor_section:
    #     print(e.get_text(separator=" ", strip=True))

    job_details = soup.select(".job-detail__information-detail")
    # for e in job_details:
    #     print(e.get_text(separator=" ", strip=True))
    print(job_details)


def premium_parse(html : str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    experience = soup.select(".basic-information-item__data")
    for e in experience:
        print(e.get_text(separator=" ", strip=True))
    

def get_page_html(url : str) -> str:
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


        page.goto(url)


        html = page.content()

        

        browser.close()
        return html
    
def print_html(html : str) -> None:
    print(html)

    

url = "https://www.topcv.vn/viec-lam/devops-engineer-ha-noi/2103701.html?ta_source=JobSearchList_LinkDetail&u_sr_id=WFqapEbhH6bZXJ2kh4VCXesMpci1ykUrSXT43a7y_1783584911"
premium_url = "https://www.topcv.vn/brand/fptsoftwareacademy/tuyen-dung/thuc-tap-sinh-devops-j1683787.html?ta_source=JobSearchList_LinkDetail&u_sr_id=WFqapEbhH6bZXJ2kh4VCXesMpci1ykUrSXT43a7y_1783584911"
html = get_page_html("https://www.topcv.vn/tim-viec-lam-moi-nhat?company_field=1&type_keyword=1&sba=1&saturday_status=0")

print_html(html=html)