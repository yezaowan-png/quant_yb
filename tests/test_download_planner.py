import unittest

import pandas as pd

from data.download_planner import estimate_download_plan


def _cached(covers: bool, adj_ok: bool = True) -> pd.DataFrame:
    df = pd.DataFrame([{"date": "20260102"}])
    df.attrs["covers"] = covers
    df.attrs["adj_ok"] = adj_ok
    return df


class DownloadPlannerTest(unittest.TestCase):
    def test_estimate_counts_cache_hits_and_api_calls(self):
        symbols = ["000001.SZ", "600519.SH", "000001.SH"]
        cached_by_symbol = {
            "000001.SZ": _cached(covers=True, adj_ok=True),
            "600519.SH": _cached(covers=True, adj_ok=False),
            "000001.SH": _cached(covers=True, adj_ok=False),
        }

        plan = estimate_download_plan(
            symbols=symbols,
            cached_by_symbol=cached_by_symbol,
            start="20260101",
            end="20260131",
            force=False,
            effective_rpm=120,
            cache_covers_range=lambda cached, _start, _end: bool(cached is not None and cached.attrs["covers"]),
            is_index_symbol=lambda symbol: symbol == "000001.SH",
            stock_cache_matches_adjustment=lambda cached: bool(cached is not None and cached.attrs["adj_ok"]),
            estimate_api_calls_for_request=lambda symbol, cached, _start, _end, _force: (
                0
                if cached is not None and cached.attrs["covers"] and (symbol == "000001.SH" or cached.attrs["adj_ok"])
                else 2
            ),
        )

        self.assertEqual(plan.total, 3)
        self.assertEqual(plan.cached_count, 2)
        self.assertEqual(plan.need_api, 1)
        self.assertEqual(plan.api_calls, 2)
        self.assertEqual(plan.estimated_seconds, 1.0)

    def test_force_ignores_cache_hits(self):
        plan = estimate_download_plan(
            symbols=["000001.SZ", "600519.SH"],
            cached_by_symbol={
                "000001.SZ": _cached(covers=True),
                "600519.SH": _cached(covers=True),
            },
            start="20260101",
            end="20260131",
            force=True,
            effective_rpm=60,
            cache_covers_range=lambda cached, _start, _end: True,
            is_index_symbol=lambda _symbol: False,
            stock_cache_matches_adjustment=lambda _cached: True,
            estimate_api_calls_for_request=lambda _symbol, cached, _start, _end, force: 3 if force and cached is None else 0,
        )

        self.assertEqual(plan.cached_count, 0)
        self.assertEqual(plan.need_api, 2)
        self.assertEqual(plan.api_calls, 6)
        self.assertEqual(plan.estimated_seconds, 6.0)

    def test_effective_rpm_is_never_below_one(self):
        plan = estimate_download_plan(
            symbols=["000001.SZ"],
            cached_by_symbol={},
            start="20260101",
            end="20260131",
            force=True,
            effective_rpm=0,
            cache_covers_range=lambda _cached, _start, _end: False,
            is_index_symbol=lambda _symbol: False,
            stock_cache_matches_adjustment=lambda _cached: False,
            estimate_api_calls_for_request=lambda *_args: 1,
        )

        self.assertEqual(plan.effective_rpm, 1)
        self.assertEqual(plan.estimated_seconds, 60.0)


if __name__ == "__main__":
    unittest.main()
