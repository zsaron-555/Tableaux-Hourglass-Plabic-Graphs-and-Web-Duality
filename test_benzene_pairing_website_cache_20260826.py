from __future__ import annotations

import unittest
from pathlib import Path

from benzene_pairing_cache_20260826 import BenzenePairingCache
import wrench_web_app_0714 as website


ROOT = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "benzene_pairing_cache_0826.json.gz"


class BenzenePairingCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cache = BenzenePairingCache.load(CACHE_PATH)

    def test_complete_presentation_universe(self) -> None:
        summary = self.cache.summary()
        self.assertEqual(summary["w_presentation_count"], 2816)
        self.assertEqual(summary["x_presentation_count"], 24728)
        self.assertEqual(summary["nonzero_pairing_count"], 5796)

    def test_explicit_nonzero_and_complete_coverage_zero(self) -> None:
        w_id = "rep0086_rho00_1111223223443344__bottom"
        nonzero_x = "catalogue_X_10353_1123211344223434"
        zero_x = "benzene_X_10353_1123211344223434__middle"
        nonzero = self.cache.lookup(w_id, nonzero_x)
        zero = self.cache.lookup(w_id, zero_x)
        self.assertIsNotNone(nonzero)
        self.assertIsNotNone(zero)
        self.assertEqual(nonzero.value, 1)  # type: ignore[union-attr]
        self.assertEqual(nonzero.value_source, "stored_nonzero")  # type: ignore[union-attr]
        self.assertEqual(zero.value, 0)  # type: ignore[union-attr]
        self.assertEqual(  # type: ignore[union-attr]
            zero.value_source, "certified_zero_complete_coverage"
        )

    def test_x_presentation_is_not_collapsed_by_word(self) -> None:
        w_id = "rep0086_rho00_1111223223443344__bottom"
        x_ids = (
            "catalogue_X_10353_1123211344223434",
            "benzene_X_10353_1123211344223434__middle",
            "benzene_X_10353_1123211344223434__top",
        )
        self.assertEqual(
            [self.cache.lookup(w_id, x_id).value for x_id in x_ids],  # type: ignore[union-attr]
            [1, 0, 0],
        )

    def test_chain_value_and_dataset_status(self) -> None:
        lookup = self.cache.lookup(
            "rep0147_rho00_1111223322344434__bottom",
            "benzene_X_20863_1231121243324344__top",
        )
        self.assertIsNotNone(lookup)
        self.assertEqual(lookup.value, -1)  # type: ignore[union-attr]
        self.assertEqual(lookup.dataset["conjecture_status"], "verified")  # type: ignore[union-attr]


class BenzenePairingWebsiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        website.BENZENE_PAIRING_CACHE_PATH = CACHE_PATH
        website._BENZENE_PAIRING_CACHE = None
        website._BENZENE_PAIRING_CACHE_ERROR = None

    def test_presentation_endpoint_options_use_exact_ids(self) -> None:
        options = website.benzene_presentation_options(
            "1123211344223434", "X"
        )
        self.assertTrue(options["authoritative_pairing_cache"])
        self.assertEqual(len(options["options"]), 3)
        self.assertEqual(
            options["selected"], "catalogue_X_10353_1123211344223434"
        )
        self.assertEqual(
            {item["representation"] for item in options["options"]},
            {"bottom", "middle", "top"},
        )

    def test_run_prefers_cached_value_over_legacy_engine(self) -> None:
        params = {
            "w": "1111223223443344",
            "x": "1123211344223434",
            "w_presentation_id": "rep0086_rho00_1111223223443344__bottom",
            "x_presentation_id": "catalogue_X_10353_1123211344223434",
        }
        lookup = website.lookup_cached_pairing(params)
        self.assertIsNotNone(lookup)
        self.assertEqual(lookup.value, 1)  # type: ignore[union-attr]
        page = website.run_pair(params)
        self.assertIn("Authoritative Cached Pairing Result", page)
        self.assertIn("Final pairing value", page)
        self.assertIn(">1<", page)

    def test_unknown_pair_remains_available_to_legacy_fallback(self) -> None:
        self.assertIsNone(
            website.lookup_cached_pairing(
                {"w": "not_in_cache", "x": "also_not_in_cache"}
            )
        )


if __name__ == "__main__":
    unittest.main()
