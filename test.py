from typing import Any

import requests


def fetch_job(job_id: int) -> dict[str, Any]:
    url = f"https://api.topdev.vn/td/v2/jobs/{job_id}"

    params = {
        "fields[job]": ",".join(
            [
                "id",
                "content",
                "requirements_arr",
                "requirements_original",
                "responsibilities",
                "responsibilities_original",
                "benefits_v2",
            ]
        ),
        "locale": "en_US",
    }

    headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/150.0.0.0 Safari/537.36"
        ),
    }

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=20,
    )

    response.raise_for_status()
    return response.json()


job = fetch_job(2115440)

print(type(job))

