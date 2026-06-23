from app.store import QuoteStore
from app.models import Quote
from tests.test_models import make_quote_input


def _quote() -> Quote:
    return Quote(quote_ref="Q-AB12CDE", annual_premium=642.12,
                 monthly_premium=53.51, input=make_quote_input())


def test_save_returns_guid_and_get_roundtrips():
    store = QuoteStore()
    guid = store.save(_quote())
    assert isinstance(guid, str) and len(guid) == 36
    fetched = store.get(guid)
    assert fetched is not None and fetched.quote_ref == "Q-AB12CDE"


def test_guids_are_unique_and_unknown_returns_none():
    store = QuoteStore()
    g1 = store.save(_quote()); g2 = store.save(_quote())
    assert g1 != g2
    assert store.get("not-a-real-guid") is None
