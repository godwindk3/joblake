from bs4 import BeautifulSoup

FILE_NAME = "html_test.txt"

def file_reader(file_name: str) -> str:
    with open(file_name, "r", encoding="utf-8") as file:
        html_content = file.read()
    
    return html_content

html = file_reader(FILE_NAME)
