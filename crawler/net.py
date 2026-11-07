import re
import time

import requests

MAX_WAIT_SECONDS = 300
_SECRET = re.compile(r"((?:key|access_token|client_secret)=)[^&\s]+|AIza[0-9A-Za-z_-]{20,}", re.IGNORECASE)


def redact(text: str) -> str:
    return _SECRET.sub(lambda m: (m.group(1) or "") + "***", text or "")


class QuotaExceeded(RuntimeError):
    pass


class RateLimited(RuntimeError):
    def __init__(self, seconds: float):
        super().__init__(f"Bị giới hạn tốc độ, nền tảng yêu cầu chờ {seconds / 3600:.1f} giờ")
        self.seconds = seconds


def get_json(session: requests.Session, url: str, *, params: dict | None = None, headers: dict | None = None, max_retries: int = 5) -> dict:
    delay = 2.0
    for attempt in range(max_retries):
        try:
            resp = session.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as ex:
            if attempt == max_retries - 1:
                raise requests.RequestException(redact(str(ex))) from None
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", delay))
            if wait > MAX_WAIT_SECONDS:
                raise RateLimited(wait)
            time.sleep(wait + 1)
            delay *= 2
            continue
        if resp.status_code >= 500:
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code == 403 and "quota" in resp.text.lower():
            raise QuotaExceeded(redact(resp.text[:300]))
        if resp.status_code >= 400:
            raise requests.HTTPError(f"{resp.status_code} {resp.reason}: {redact(resp.url)}", response=resp)
        return resp.json()
    raise RuntimeError(f"Hết lượt thử lại: {redact(url)}")
