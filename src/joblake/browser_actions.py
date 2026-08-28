from joblake.models import FetchError


def run_browser_actions(page, config: dict) -> None:
    """Run configured post-navigation browser interactions."""
    actions = config.get("browser_actions", [])

    if not isinstance(actions, list):
        raise ValueError(
            "browser_actions must be a list"
        )

    for action_config in actions:
        if not isinstance(action_config, dict):
            raise ValueError(
                "Each browser action must be a mapping"
            )

        action = action_config.get("action")
        wait_after_ms = int(
            action_config.get("wait_after_ms", 0)
        )

        if wait_after_ms < 0:
            raise ValueError(
                "browser action wait_after_ms "
                "cannot be negative"
            )

        if action == "scroll":
            _run_scroll(
                page,
                action_config,
                wait_after_ms,
            )
            continue

        if action == "click":
            _run_click(
                page,
                action_config,
                wait_after_ms,
            )
            continue

        raise ValueError(
            f"Unsupported browser action: {action}"
        )


def _run_scroll(
    page,
    action_config: dict,
    wait_after_ms: int,
) -> None:
    times = int(action_config.get("times", 1))
    delta_x = int(action_config.get("delta_x", 0))
    delta_y = int(
        action_config.get("delta_y", 1000)
    )

    if times < 0:
        raise ValueError(
            "scroll action times cannot be negative"
        )

    for _ in range(times):
        page.mouse.wheel(delta_x, delta_y)

        if wait_after_ms:
            page.wait_for_timeout(wait_after_ms)


def _run_click(
    page,
    action_config: dict,
    wait_after_ms: int,
) -> None:
    selector = action_config.get("selector")

    if not selector:
        raise ValueError(
            "click action requires selector"
        )

    locator = page.locator(selector)

    if locator.count() == 0:
        if action_config.get("optional", False):
            return

        raise FetchError(
            "Required browser action selector "
            f"not found: {selector}"
        )

    target = locator.first

    if action_config.get(
        "scroll_into_view",
        False,
    ):
        target.scroll_into_view_if_needed()

    target.click()

    if wait_after_ms:
        page.wait_for_timeout(wait_after_ms)
