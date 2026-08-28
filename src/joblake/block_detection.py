def detect_block_reason(
    status_code: int | None,
    html: str,
) -> str | None:
    """Return a block reason only when signals are strong enough.

    A normal page may load Cloudflare Turnstile from
    challenges.cloudflare.com, so that hostname alone is not evidence of
    a page-level challenge.
    """
    html_preview = html[:200_000].lower()

    has_cloudflare_host = (
        "challenges.cloudflare.com" in html_preview
    )
    has_cloudflare_challenge_data = (
        "cf-chl-" in html_preview
    )
    has_challenge_form = (
        'id="challenge-form"' in html_preview
        or "id='challenge-form'" in html_preview
    )
    has_challenge_title = (
        "<title>just a moment" in html_preview
    )

    if (
        has_challenge_title
        or (
            has_cloudflare_challenge_data
            and has_challenge_form
        )
        or (
            status_code in {403, 503}
            and has_cloudflare_host
        )
    ):
        return "Cloudflare challenge"

    captcha_markers = (
        "<title>captcha",
        "<title>verify",
        "verify you are human",
        "xác minh bạn là con người",
    )

    if any(
        marker in html_preview
        for marker in captcha_markers
    ):
        return "CAPTCHA challenge"

    rate_limit_markers = (
        "too many requests",
        "rate limit exceeded",
    )

    if any(
        marker in html_preview
        for marker in rate_limit_markers
    ):
        return "rate-limit page"

    if status_code == 403:
        return "HTTP 403 access denied"

    return None
