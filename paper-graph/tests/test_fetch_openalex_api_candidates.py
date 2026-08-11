import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "fetch_openalex_api_candidates.py"
SPEC = importlib.util.spec_from_file_location("fetch_openalex_api_candidates", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_channel_filter_uses_validated_exact_title_abstract_search() -> None:
    value = MODULE.channel_filter(MODULE.CHANNELS["finance_core"], "2016-01-01")

    assert "title_and_abstract.search.exact:" in value
    assert "primary_topic.field.id:20" in value
    assert "from_publication_date:2016-01-01" in value


def test_request_url_never_includes_empty_api_key() -> None:
    value = MODULE.request_url(
        channel=MODULE.CHANNELS["finance_core"],
        min_date="2016-01-01",
        cursor="*",
        api_key=None,
    )

    assert "api_key=" not in value
    assert "per_page=100" in value
    assert "cursor=%2A" in value


def test_retry_delay_honors_retry_after_and_is_bounded() -> None:
    assert MODULE._retry_delay({"Retry-After": "17"}, 0) == 17.0
    assert MODULE._retry_delay({"Retry-After": "999"}, 0) == 300.0
    assert MODULE._retry_delay({}, 3) == 8.0
