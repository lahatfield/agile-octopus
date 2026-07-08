import datetime as dt

from core.octopus import (
    RateSlot,
    fetch_agile_rates,
    filter_negative_slots,
    filter_ok_slots,
    filter_spike_slots,
    get_current_agile_product_code,
)

UTC = dt.timezone.utc


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self._payload = payload

    def get(self, url, params=None):
        return FakeResponse(self._payload)


class SequentialFakeSession:
    """Returns a different canned payload on each successive .get() call."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self._call_count = 0

    def get(self, url, params=None):
        payload = self._payloads[self._call_count]
        self._call_count += 1
        return FakeResponse(payload)


def _make_slot(value_inc_vat: float) -> RateSlot:
    return RateSlot(
        valid_from=dt.datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        valid_to=dt.datetime(2026, 1, 1, 0, 30, tzinfo=UTC),
        value_inc_vat=value_inc_vat,
        value_exc_vat=value_inc_vat,
    )


def test_filter_ok_slots_keeps_non_negative_slots_at_or_below_threshold():
    # Prices straddling the threshold: below, exactly at, and above.
    slots = []

    for i in range(3):
        value = 5.0*i
        slot = _make_slot(value_inc_vat=value)
        slots.append(slot)

    result = filter_ok_slots(slots=slots, threshold=5.0)
    assert result == [slots[0], slots[1]]


def test_filter_negative_slots_keeps_only_strictly_negative():
    slots = [_make_slot(-1.0), _make_slot(0.0), _make_slot(5.0)]
    result = filter_negative_slots(slots)
    assert result == [slots[0]]


def test_filter_spike_slots_keeps_only_strictly_above_threshold():
    # Prices straddling the threshold: below, exactly at, and above.
    slots = [_make_slot(0.0), _make_slot(5.0), _make_slot(10.0)]
    result = filter_spike_slots(slots, threshold=5.0)
    assert result == [slots[2]]


def test_get_current_agile_product_code_picks_active_import_product():
    # One product covering each exclusion reason, plus the one that should win.
    payload = {
    "results": [
        # Code not starting with AGILE.
        {
            "code": "STUCK-24-10-01",
            "direction": "IMPORT",
            "available_from": "2024-10-01T00:00:00Z",
            "available_to": None,
        },
        # Available from in the future.
        {
            "code": "AGILE-WRONG-1",
            "direction": "IMPORT",
            "available_from": "2026-10-01T00:00:00Z",
            "available_to": None,
        },
        # Available to in the past.
        {
            "code": "AGILE-WRONG-2",
            "direction": "IMPORT",
            "available_from": "2024-10-01T00:00:00Z",
            "available_to": "2025-10-01T00:00:00Z",
        },
        # EXPORT rather than IMPORT tariff.
        {
            "code": "AGILE-WRONG-3",
            "direction": "EXPORT",
            "available_from": "2024-10-01T00:00:00Z",
            "available_to": None,
        },
        # Correct choice.
        {
            "code": "AGILE-24-10-01",
            "direction": "IMPORT",
            "available_from": "2024-10-01T00:00:00Z",
            "available_to": None,
        },
    ]
    }
    session = FakeSession(payload)
    result = get_current_agile_product_code(session=session)
    assert result == "AGILE-24-10-01"


def test_fetch_agile_rates_follows_pagination():
    page_1 = {
        "next": "https://api.octopus.energy/v1/products/AGILE-24-10-01/electricity-tariffs/E-1R-AGILE-24-10-01-P/standard-unit-rates/?page=2",
        "results": [
            {
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_to": "2026-01-01T00:30:00Z",
                "value_inc_vat": 10.0,
                "value_exc_vat": 9.5,
            },
        ],
    }
    page_2 = {
        "next": None,
        "results": [
            {
                "valid_from": "2026-01-01T00:30:00Z",
                "valid_to": "2026-01-01T01:00:00Z",
                "value_inc_vat": 12.0,
                "value_exc_vat": 11.4,
            },
        ],
    }

    session = SequentialFakeSession([page_1, page_2])
    result = fetch_agile_rates(
        "AGILE-24-10-01",
        "P",
        dt.datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        dt.datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
        session=session,
    )

    assert len(result) == 2
    assert result[0].value_inc_vat == 10.0
    assert result[1].value_inc_vat == 12.0

