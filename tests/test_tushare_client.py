import threading
import unittest
from unittest.mock import patch

from data.tushare_client import RateLimiter, TushareClient, configured_tokens, is_rate_limit_error


class TushareClientTest(unittest.TestCase):
    def test_configured_tokens_deduplicates_primary_and_extra_tokens(self):
        config = {
            "tushare": {
                "token": " token-a ",
                "tokens": ["token-a", "token-b", "", None],
            }
        }

        self.assertEqual(configured_tokens(config), ["token-a", "token-b"])

    def test_configured_tokens_requires_at_least_one_token(self):
        with self.assertRaisesRegex(ValueError, "缺少 Tushare token"):
            configured_tokens({"tushare": {"token": "", "tokens": []}})

    def test_call_uses_factory_and_returns_result(self):
        created = []

        def pro_factory(token):
            created.append(token)
            return {"token": token}

        client = TushareClient(
            ["token-a", "token-b"],
            calls_per_minute=6000,
            safety_ratio=1,
            retries=0,
            pro_factory=pro_factory,
        )

        result = client.call("000001.SZ", "daily", lambda pro: pro["token"])

        self.assertEqual(created, ["token-a", "token-b"])
        self.assertEqual(result, "token-a")
        self.assertEqual(client.effective_calls_per_minute, 12000)

    def test_call_skips_token_that_is_cooling_down(self):
        def pro_factory(token):
            return {"token": token}

        client = TushareClient(
            ["token-a", "token-b"],
            calls_per_minute=6000,
            safety_ratio=1,
            retries=0,
            pro_factory=pro_factory,
        )
        client._api_slots[0]["limiter"].cooldown(60)

        result = client.call("000001.SZ", "daily", lambda pro: pro["token"])

        self.assertEqual(result, "token-b")

    def test_rate_limit_error_retries_once(self):
        calls = []

        def pro_factory(token):
            return {"token": token}

        client = TushareClient(
            ["token-a"],
            calls_per_minute=6000,
            safety_ratio=1,
            retries=1,
            backoff_seconds=0,
            pro_factory=pro_factory,
        )

        def flaky(_pro):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("抱歉，您访问接口(daily)频率超限")
            return "ok"

        with patch("click.echo"):
            self.assertEqual(client.call("000001.SZ", "daily", flaky), "ok")

        self.assertEqual(len(calls), 2)

    def test_call_respects_cancel_event_before_request(self):
        event = threading.Event()
        event.set()
        client = TushareClient(
            ["token-a"],
            calls_per_minute=6000,
            safety_ratio=1,
            retries=0,
            cancel_event=event,
            pro_factory=lambda token: {"token": token},
        )

        with self.assertRaises(KeyboardInterrupt):
            client.call("000001.SZ", "daily", lambda _pro: "unreachable")

    def test_rate_limiter_can_cancel_while_waiting(self):
        event = threading.Event()
        limiter = RateLimiter(calls_per_minute=60, safety_ratio=1)
        limiter.wait(event)
        event.set()

        with self.assertRaises(KeyboardInterrupt):
            limiter.wait(event)

    def test_is_rate_limit_error_matches_tushare_message(self):
        self.assertTrue(is_rate_limit_error(RuntimeError("访问接口(daily)频率超限")))
        self.assertFalse(is_rate_limit_error(RuntimeError("network timeout")))


if __name__ == "__main__":
    unittest.main()
