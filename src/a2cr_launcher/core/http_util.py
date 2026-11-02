from random import uniform
from time import sleep

import requests

from a2cr_launcher.core.download import MAX_RETRY, TIMEOUT, get_session


def http_get(url: str, **kwargs) -> requests.Response:
    """带重试的 GET，失败时抛出最后一次的异常，方便上层显示具体原因。"""
    last_error: requests.RequestException | None = None
    for attempt in range(MAX_RETRY):
        try:
            response = get_session().get(url, timeout=TIMEOUT, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < MAX_RETRY:
                sleep(min(0.5 * 2 ** attempt, 4.0) + uniform(0, 0.3))
    raise last_error if last_error is not None else requests.RequestException(f"无法访问 {url}")
