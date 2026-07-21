from bs4 import BeautifulSoup

FILE_NAME = "html_test.txt"

def file_reader(file_name: str) -> str:
    with open(file_name, "r", encoding="utf-8") as file:
        html_content = file.read()
    
    return html_content

def parse(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one("h1.box-header-job__title").get_text().strip()
    common_infor = soup.select("div.list-info__content__desc")
    place = common_infor[0].get_text().strip()
    experience = common_infor[1].get_text().strip()
    deadline_apply = common_infor[2].get_text().strip()
    

    print(f"Tittle: {title}, Place: {place}, Experience: {experience}, Deadline_Apply: {deadline_apply}")
    time_and_place = soup.select("div.box-job-information-address-and-time-list")
    
    # job details

    job_details = soup.select("div.box-job-information-detail-item__text")

    job_describle = job_details[0].get_text().strip()
    requirement = job_details[1].get_text().strip()
    benefit = job_details[2].get_text().strip()

    place_detail = time_and_place[0]
    time_detail = time_and_place[1]

    company_infor_details = soup.select("div.box-company-info-detail")

    job_common_infor = soup.select("div.box-job-information-detail-item.box-job-information-general-info")

    # get_text(job_common_infor)



def get_text(infor_parse: list[str]) -> str:
    for text in infor_parse:
        print(text.get_text().strip()) 

html = file_reader(FILE_NAME)
parse(html)

