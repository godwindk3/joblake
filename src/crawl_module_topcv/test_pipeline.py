from discovery_pages import fetch_all_it_jobs_pages
from discovery_urls_in_pages import extract_urls_from_html_pages
from details import process_crawled_details

base_url = "https://www.topcv.vn/tim-viec-lam-cong-nghe-thong-tin-cr257"
html_pages = fetch_all_it_jobs_pages(base_url=base_url, total_pages=3)
urls = extract_urls_from_html_pages(html_pages)
# print(len(urls))
process_crawled_details(urls)