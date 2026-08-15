#!/usr/bin/env python3
"""Regression tests for the direct SL4 benzene-surgery checker."""

from __future__ import annotations

import unittest
from pathlib import Path

from audit_benzene_conjecture_20260803 import (
    graph_model,
    induced_internal_six_cycles,
    is_benzene,
)
from check_benzene_surgery_pairing import (
    alternating_two_hourglass_squares,
    enumerate_benzene_surgery_channels,
    load_ribbon_web,
    perform_benzene_surgery,
    reduce_alternating_two_hourglass_square,
    ribbon_isomorphism,
    transpose_word,
)


ROOT = Path(__file__).resolve().parent
GRAPH_DIR = ROOT / "4x4_All_graph_data"


def graph_path(word: str) -> Path:
    matches = list(GRAPH_DIR.glob(f"*_{word}.json"))
    if len(matches) != 1:
        raise AssertionError(f"Expected one graph for {word}, found {matches}.")
    return matches[0]


class BenzeneSurgeryPairingTest(unittest.TestCase):
    def test_transpose_word(self) -> None:
        self.assertEqual(
            transpose_word("1121324314234234"),
            "1213121242333444",
        )

    def test_representative_159_direct_surgery_channel(self) -> None:
        source_path = graph_path("1111223324234434")
        expected_path = graph_path("1121324314234234")
        model = graph_model(source_path)
        benzenes = [
            cycle
            for cycle in induced_internal_six_cycles(model)
            if is_benzene(cycle, model.edge_kind)
        ]
        self.assertEqual(len(benzenes), 1)

        surgery = perform_benzene_surgery(
            load_ribbon_web(source_path),
            benzenes[0],
            splice_side_kind="H",
        )
        self.assertIsNotNone(
            ribbon_isomorphism(surgery.web, load_ribbon_web(expected_path))
        )
        self.assertEqual(
            transpose_word("1121324314234234"),
            "1213121242333444",
        )

    def test_representative_253_has_direct_and_chain_reaction_surgeries(self) -> None:
        source_path = graph_path("1111232234234434")
        model = graph_model(source_path)
        channels = enumerate_benzene_surgery_channels(
            load_ribbon_web(source_path),
            induced_internal_six_cycles(model),
        )

        self.assertEqual(len(channels), 2)
        self.assertEqual(
            [channel.channel_type for channel in channels],
            ["direct", "chain_reaction"],
        )
        self.assertEqual(len(channels[0].benzene_move_path), 0)
        self.assertEqual(len(channels[1].benzene_move_path), 1)
        self.assertNotEqual(channels[0].cycle, channels[1].cycle)

        direct_expected = load_ribbon_web(graph_path("1121342134234234"))
        self.assertIsNotNone(
            ribbon_isomorphism(channels[0].surgery.web, direct_expected)
        )
        self.assertEqual(
            transpose_word("1121342134234234"),
            "1213112422333444",
        )

        chain_squares = alternating_two_hourglass_squares(channels[1].surgery.web)
        self.assertEqual(len(chain_squares), 1)
        normalized = reduce_alternating_two_hourglass_square(
            channels[1].surgery.web,
            chain_squares[0],
        )
        chain_expected = load_ribbon_web(graph_path("1112341234234234"))
        self.assertIsNotNone(ribbon_isomorphism(normalized.web, chain_expected))
        self.assertEqual(
            transpose_word("1112341234234234"),
            "1231114222333444",
        )


if __name__ == "__main__":
    unittest.main()
