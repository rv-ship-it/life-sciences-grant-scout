from abc import ABC, abstractmethod
from typing import Generator
import requests
import time
import logging


class BaseFetcher(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "GrantScout/2.0 (research-grant-scanner)"
        })
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def fetch(self) -> Generator:
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        ...

    def _request_with_retry(self, method: str, url: str,
                            max_retries: int = 3, **kwargs) -> requests.Response:
        timeout = self.config.get("timeout", 30)
        for attempt in range(max_retries):
            try:
                resp = self.session.request(method, url, timeout=timeout, **kwargs)
                if resp.status_code == 429:
                    wait = min(2 ** (attempt + 1), 60)
                    self.logger.warning(f"Rate limited, waiting {wait}s")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"Failed after {max_retries} attempts: {e}")
                    raise
                time.sleep(2 ** attempt)
