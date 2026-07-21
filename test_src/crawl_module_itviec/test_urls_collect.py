import requests
from bs4 import BeautifulSoup


def fetch(url: str) -> str:
    response = requests.get(url)
    response.raise_for_status()
    
    return response.text

def extract_urls_from_page(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    h3_tags = soup.find_all("h3", class_="imt-3 text-break")
    urls = [
        h3.get("data-url")
        for h3 in h3_tags
    ]

    print(urls)


    

# urls = "https://itviec.com/it-jobs/ho-chi-minh-hcm"

# html = fetch(urls)
# extract_urls_from_page(html)