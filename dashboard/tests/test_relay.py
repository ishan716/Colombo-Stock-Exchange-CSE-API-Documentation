"""STOMP framing and the epoch-vs-ISO timestamp normalisation."""
from dashboard.server.ws_relay import _frame, _parse, normalise


def test_frame_roundtrip():
    raw = _frame("SEND", {"destination": "/app/request-aspi"})
    assert raw.endswith("\x00")
    command, headers, body = _parse(raw)
    assert command == "SEND"
    assert headers["destination"] == "/app/request-aspi"
    assert body == ""


def test_parse_message_with_body():
    raw = ("MESSAGE\ndestination:/topic/aspi\ncontent-type:application/json\n\n"
           '{"value":21657.99}\x00')
    command, headers, body = _parse(raw)
    assert command == "MESSAGE"
    assert headers["destination"] == "/topic/aspi"
    assert body == '{"value":21657.99}'


def test_iso_timestamp_becomes_epoch_ms():
    """Broadcasts send ISO-8601 where replies send epoch ints."""
    out = normalise({"value": 1.0, "timestamp": "2026-09-07T06:41:48.539+0000"})
    assert isinstance(out["timestamp"], int)
    assert out["timestamp"] == 1788763308539


def test_epoch_timestamp_passes_through():
    out = normalise({"timestamp": 1788763289020})
    assert out["timestamp"] == 1788763289020


def test_normalise_recurses_into_lists():
    out = normalise([{"symbol": "A", "tradeDate": "2026-09-07T09:09:13.000+0000"}])
    assert isinstance(out[0]["tradeDate"], int)


def test_unparseable_timestamp_is_left_alone():
    out = normalise({"timestamp": "not a date"})
    assert out["timestamp"] == "not a date"


def test_non_time_fields_untouched():
    out = normalise({"symbol": "AAIC.N0000", "price": 82.2})
    assert out == {"symbol": "AAIC.N0000", "price": 82.2}
