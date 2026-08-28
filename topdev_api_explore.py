import requests

cookies = {
    '_ga': 'GA1.1.828800155.1759738377',
    '_ga_7X6VBRP2ER': 'GS2.1.s1759740630$o2$g0$t1759740630$j60$l0$h0',
    '_ga_S0JFGXYD51': 'GS2.1.s1759740630$o2$g0$t1759740630$j60$l0$h0',
    'visitor': 'eyJpdiI6IjNhc21wV0lmTzBoT0NvQXdiQ1I3ZHc9PSIsInZhbHVlIjoiVVBHdTR6VjBvejhpbmx0YUdpbkU0dGJoTTVYODZIdUdVRWl0U2dsTDhranFVL2lvbzNnZUdhMVFBRU9nMXBXd3B0dWxiVUprd1ZHWUl1d3FwQmgvSnZUVzF4ZWVoeDBFRTh4aDl4MmRjZndFMWJwNjlGclV4WHBVMmNZcTBoQ1Y3SFJmRWh6YnRRQ1hhcmlpWmFRMEp3aytkZGxIeGZtb2s3cy9JTG4vNzYwPSIsIm1hYyI6IjMwZjA4ODNjMGIyNDllN2M5ZDRhNTM4NDkzNTJmNDcxZTE0NTg4NDhiNzI5M2M3ZmEyMzYwY2IzYzYzNjcwNTkiLCJ0YWciOiIifQ%3D%3D',
    '_fbp': 'fb.1.1779787109579.707542975842191614',
    '_clck': '1s9n0sm%5E2%5Eg6d%5E0%5E2337',
    '__gads': 'ID=8ca579caca197548:T=1779787119:RT=1779787119:S=ALNI_MYJcnEA4C3r1J98rV7wClznbVGtHA',
    '__gpi': 'UID=0000143f003c72ce:T=1779787119:RT=1779787119:S=ALNI_MZEY_XEZhw2vsKLPlrrSu_VzqW0BQ',
    '__eoi': 'ID=9beaeed4b8d04a99:T=1779787119:RT=1779787119:S=AA-AfjZxHmJ2O_yXNYG79_ODG31q',
    '_ga_6VMQR6N4EF': 'GS2.1.s1779787109$o1$g1$t1779787205$j48$l0$h1366533455',
    '_ga_Z1K17H6VZ0': 'GS2.1.s1779787109$o1$g1$t1779787205$j48$l0$h2104110965',
    'TDSTL_MrEHZlyk': 'eyJ1dWlkX2Nvb2tpZSI6IjdlYzllYWEwLTg3MzUtMTFmMS04NTExLTc5M2I5NTBmNzYwOCJ9',
    'TDSTL_eYhvgvlx': 'eyJ1dWlkX2Nvb2tpZSI6Ijg5MDBkZTkwLTg3MzUtMTFmMS1iYzUyLTYzYjQ2NWU3ZTlmYyJ9',
    'topdev_locale': 'en',
    'job_apply_tracking': '%7B%22src%22%3A%22topdev_home%22%2C%22medium%22%3A%22superhotjobs%22%7D',
    'ta': 'eyJpdiI6ImZWQXAvSk9IVXFLanlybUZSMVkrN1E9PSIsInZhbHVlIjoibTJ3UU52UWF2M0REZm1vRmU4UzhFV1BXVnNpNC9RYmJGVWhEb1pWaVp2UFU2TkVCSFVVSG55QW5VdDJsMkY2SjF1aGh3c3Y0RURDWkp6bks0MDJRSWc9PSIsIm1hYyI6IjM1Njg1N2Y0ZTViOGRhMmEzYmViZTQxNWJmYzdiMTViYTI5ZmUxYWY3ZTY3NDFkY2IxZjgwNjMxZTQ2ZmRhOTciLCJ0YWciOiIifQ%3D%3D',
    'TDSID': 'eyJpdiI6IllqdzZpcTU3YXY2WE5GMXgxTUtRL0E9PSIsInZhbHVlIjoiSERIVCtPSGhKWUZ3OUwveUFSYjcycUo5WWhKUW1Ic2ZqU0I4V0t4eW1nbGNKdk5Gbm8ySmJaV29QWTdkczU2SUE3RyswRmVHY21nV0g2clphbjRiRnRDT0RkKzQxblNrMXljZkY0ZGZWMnR5N0YvYjZ6Ui90S3pVUDRoWVU3SHgiLCJtYWMiOiI3YmU2NjI0M2MyZWQ5ZjU0ZmMwYWIxMDQyZWM5NjRlYmM5NTc1YTlmYmMxNzRiNDRjYzc0YTY4NWUzMjY1M2I3IiwidGFnIjoiIn0%3D',
}

headers = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'en-US,en;q=0.9,vi;q=0.8,zh-CN;q=0.7,zh;q=0.6',
    'origin': 'https://topdev.vn',
    'priority': 'u=1, i',
    'referer': 'https://topdev.vn/',
    'sec-ch-ua': '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
    'x-xsrf-token': 'eyJpdiI6IkZESHZtbWxwd1BpNW1FUUF0RzUrd3c9PSIsInZhbHVlIjoiOVlaOVdSa21Pa2dZVTZVbEJOUDFESjhoWXhpbTBpOHhDQjB4RmVxeFdkV0NDN1hEQkppcEQ0RWordmgrRmpxb2lIUnRyOHJ4T2hCWWNoSUNaUGtqMUE9PSIsIm1hYyI6IjNlNGU1ZWJlZjc0ZjA1ZDhmMjA3MTU0NjlhMmRkZmQ5MzU1ZmRkZGM5MjE3YzhiOTRjNjZlMDg3ZTJhMzFhYzQifQ==',
    # 'cookie': '_ga=GA1.1.828800155.1759738377; _ga_7X6VBRP2ER=GS2.1.s1759740630$o2$g0$t1759740630$j60$l0$h0; _ga_S0JFGXYD51=GS2.1.s1759740630$o2$g0$t1759740630$j60$l0$h0; visitor=eyJpdiI6IjNhc21wV0lmTzBoT0NvQXdiQ1I3ZHc9PSIsInZhbHVlIjoiVVBHdTR6VjBvejhpbmx0YUdpbkU0dGJoTTVYODZIdUdVRWl0U2dsTDhranFVL2lvbzNnZUdhMVFBRU9nMXBXd3B0dWxiVUprd1ZHWUl1d3FwQmgvSnZUVzF4ZWVoeDBFRTh4aDl4MmRjZndFMWJwNjlGclV4WHBVMmNZcTBoQ1Y3SFJmRWh6YnRRQ1hhcmlpWmFRMEp3aytkZGxIeGZtb2s3cy9JTG4vNzYwPSIsIm1hYyI6IjMwZjA4ODNjMGIyNDllN2M5ZDRhNTM4NDkzNTJmNDcxZTE0NTg4NDhiNzI5M2M3ZmEyMzYwY2IzYzYzNjcwNTkiLCJ0YWciOiIifQ%3D%3D; _fbp=fb.1.1779787109579.707542975842191614; _clck=1s9n0sm%5E2%5Eg6d%5E0%5E2337; __gads=ID=8ca579caca197548:T=1779787119:RT=1779787119:S=ALNI_MYJcnEA4C3r1J98rV7wClznbVGtHA; __gpi=UID=0000143f003c72ce:T=1779787119:RT=1779787119:S=ALNI_MZEY_XEZhw2vsKLPlrrSu_VzqW0BQ; __eoi=ID=9beaeed4b8d04a99:T=1779787119:RT=1779787119:S=AA-AfjZxHmJ2O_yXNYG79_ODG31q; _ga_6VMQR6N4EF=GS2.1.s1779787109$o1$g1$t1779787205$j48$l0$h1366533455; _ga_Z1K17H6VZ0=GS2.1.s1779787109$o1$g1$t1779787205$j48$l0$h2104110965; TDSTL_MrEHZlyk=eyJ1dWlkX2Nvb2tpZSI6IjdlYzllYWEwLTg3MzUtMTFmMS04NTExLTc5M2I5NTBmNzYwOCJ9; TDSTL_eYhvgvlx=eyJ1dWlkX2Nvb2tpZSI6Ijg5MDBkZTkwLTg3MzUtMTFmMS1iYzUyLTYzYjQ2NWU3ZTlmYyJ9; topdev_locale=en; job_apply_tracking=%7B%22src%22%3A%22topdev_home%22%2C%22medium%22%3A%22superhotjobs%22%7D; ta=eyJpdiI6ImZWQXAvSk9IVXFLanlybUZSMVkrN1E9PSIsInZhbHVlIjoibTJ3UU52UWF2M0REZm1vRmU4UzhFV1BXVnNpNC9RYmJGVWhEb1pWaVp2UFU2TkVCSFVVSG55QW5VdDJsMkY2SjF1aGh3c3Y0RURDWkp6bks0MDJRSWc9PSIsIm1hYyI6IjM1Njg1N2Y0ZTViOGRhMmEzYmViZTQxNWJmYzdiMTViYTI5ZmUxYWY3ZTY3NDFkY2IxZjgwNjMxZTQ2ZmRhOTciLCJ0YWciOiIifQ%3D%3D; TDSID=eyJpdiI6IllqdzZpcTU3YXY2WE5GMXgxTUtRL0E9PSIsInZhbHVlIjoiSERIVCtPSGhKWUZ3OUwveUFSYjcycUo5WWhKUW1Ic2ZqU0I4V0t4eW1nbGNKdk5Gbm8ySmJaV29QWTdkczU2SUE3RyswRmVHY21nV0g2clphbjRiRnRDT0RkKzQxblNrMXljZkY0ZGZWMnR5N0YvYjZ6Ui90S3pVUDRoWVU3SHgiLCJtYWMiOiI3YmU2NjI0M2MyZWQ5ZjU0ZmMwYWIxMDQyZWM5NjRlYmM5NTc1YTlmYmMxNzRiNDRjYzc0YTY4NWUzMjY1M2I3IiwidGFnIjoiIn0%3D',
}

response = requests.get(
    'https://api.topdev.vn/td/v2/jobs/2110325?fields[job]=id,title,content,benefits,benefits_v2,contract_types_str,contract_types_ids,requirements,salary,responsibilities,company,skills_arr,skills_ids,experiences_str,experiences_ids,experiences_arr,job_types_str,job_types_arr,job_types_ids,job_levels_str,job_levels_ids,addresses,detail_url,job_url,modified,refreshed,slug,is_applied,is_followed,meta_title,meta_description,meta_keywords,schema_job_posting,features,other_supports,recruiment_process,status_display,image_thumbnail,blog_tags,blog_posts,sidebar_image_banner_url,sidebar_image_link,is_free,is_basic,is_basic_plus,is_distinction,expires,can_edit_by_employer,content_html,device,responsibilities_original,requirements_original,benefits_original,recruitment_process_original,education_arr,education_str,education_ids,education_major_arr,education_major_str,education_major_ids,education_certificate,job_category_id&fields[company]=products,news,tagline,website,company_size,social_network,addresses,nationalities_arr,skills_ids,industries_arr,industries_ids,benefits,description,image_galleries,num_job_openings,faqs,slug,recruitment_process,num_employees&locale=en_US',
    cookies=cookies,
    headers=headers,
)