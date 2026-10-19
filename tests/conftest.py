"""Tests never touch the network: any real HTTP call fails loudly."""

import pytest
import requests


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def poison(*args, **kwargs):
        raise AssertionError(f"real network call attempted: {args[:1]}")
    monkeypatch.setattr(requests, "get", poison)
    monkeypatch.setattr(requests, "post", poison)
    for name in ("NEEDMINER_LLM", "GEMINI_API_KEY", "STACKEXCHANGE_KEY"):
        monkeypatch.delenv(name, raising=False)
