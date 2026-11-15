"""Department filtering for Amazon autocomplete responses (no network)."""
from unittest.mock import MagicMock, patch

import pytest

from kdp_scout.collectors.autocomplete import _query_autocomplete
from kdp_scout.config import get_marketplace


@pytest.mark.parametrize("requested", ["digital-text", "stripbooks"])
@pytest.mark.parametrize("returned", ["aps", "toys-and-games"])
def test_rejects_other_departments(requested, returned):
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "alias": returned,
        "suggestions": [{"value": "history jigsaw puzzles"}],
    }
    with patch("kdp_scout.collectors.autocomplete.fetch", return_value=response), \
         patch("kdp_scout.collectors.autocomplete.rate_registry.acquire"):
        assert _query_autocomplete("history j", requested, get_marketplace("us")) == []


@pytest.mark.parametrize("alias", ["digital-text", "stripbooks", "aps"])
def test_accepts_requested_department(alias):
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "alias": alias,
        "suggestions": [{"value": " History "}, {"value": ""}, {"value": "History books"}],
    }
    with patch("kdp_scout.collectors.autocomplete.fetch", return_value=response), \
         patch("kdp_scout.collectors.autocomplete.rate_registry.acquire"):
        assert _query_autocomplete("history", alias, get_marketplace("us")) == [
            ("history", 1), ("history books", 3),
        ]


def test_accepts_legacy_responses_without_alias():
    response = MagicMock(status_code=200)
    response.json.return_value = {"suggestions": [{"value": "history"}]}
    with patch("kdp_scout.collectors.autocomplete.fetch", return_value=response), \
         patch("kdp_scout.collectors.autocomplete.rate_registry.acquire"):
        assert _query_autocomplete("history", "digital-text", get_marketplace("us")) == [("history", 1)]
