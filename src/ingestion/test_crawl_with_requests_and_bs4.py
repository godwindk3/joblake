import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel

def fetch(url):
    response = requests.get(url, timeout=10)
    response.raise_for_status
    return response.text


def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    print(soup.select_one(".imy-5.paragraph").text)
    


html = fetch("https://itviec.com/it-jobs/remote-head-or-engineer-of-ai-operations-automation-cong-ty-tnhh-teenup-5400?lab_feature=preview_jd_page")
parse(html)