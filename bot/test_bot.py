import json
import unittest

from bot import equal_highs, equal_lows, find_trade_signal, place_trade


class DummyWs:
    def __init__(self):
        self.sent = []

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


def make_candle(high: float, low: float, close: float) -> dict[str, float]:
    return {"high": high, "low": low, "close": close}


class BotLogicTests(unittest.TestCase):
    def test_equal_highs_returns_true_for_flat_zone(self) -> None:
        zone = [
            make_candle(100.0, 95.0, 98.0),
            make_candle(100.1, 95.1, 97.5),
            make_candle(99.9, 94.9, 98.3),
            make_candle(100.05, 95.05, 97.8),
            make_candle(100.0, 95.0, 98.1),
        ]
        data = zone + [make_candle(102.0, 96.0, 99.0)]
        self.assertTrue(equal_highs(data))

    def test_equal_lows_returns_true_for_flat_zone(self) -> None:
        zone = [
            make_candle(102.0, 90.0, 95.0),
            make_candle(102.1, 90.1, 95.5),
            make_candle(101.9, 89.9, 94.8),
            make_candle(102.05, 90.05, 95.2),
            make_candle(102.0, 90.0, 95.1),
        ]
        data = zone + [make_candle(103.0, 88.0, 91.0)]
        self.assertTrue(equal_lows(data))

    def test_find_trade_signal_put(self) -> None:
        zone = [
            make_candle(100.0, 95.0, 98.0),
            make_candle(100.1, 95.1, 97.5),
            make_candle(99.9, 94.9, 98.3),
            make_candle(100.05, 95.05, 97.8),
            make_candle(100.0, 95.0, 98.1),
        ]
        data = zone + [make_candle(102.0, 96.0, 99.0)]
        self.assertEqual(find_trade_signal(data), "PUT")

    def test_find_trade_signal_call(self) -> None:
        zone = [
            make_candle(102.0, 90.0, 95.0),
            make_candle(102.1, 90.1, 95.5),
            make_candle(101.9, 89.9, 94.8),
            make_candle(102.05, 90.05, 95.2),
            make_candle(102.0, 90.0, 95.1),
        ]
        data = zone + [make_candle(102.0, 88.0, 91.0)]
        self.assertEqual(find_trade_signal(data), "CALL")

    def test_place_trade_sends_correct_payload(self) -> None:
        ws = DummyWs()
        place_trade(ws, "CALL")

        self.assertEqual(len(ws.sent), 1)
        payload = ws.sent[0]
        self.assertEqual(payload["buy"], 1)
        self.assertEqual(payload["parameters"]["contract_type"], "CALL")
        self.assertEqual(payload["parameters"]["symbol"], "R_100")


if __name__ == "__main__":
    unittest.main()
