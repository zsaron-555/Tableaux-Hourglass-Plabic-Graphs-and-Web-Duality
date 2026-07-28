import copy
import unittest

import Wrench_or_Skein_0714 as wrench


class DoubleEdgeSkeinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.colors = {10: "white", 20: "black"}

    def lens_fixture(self):
        return {
            1: [10],
            2: [10],
            10: [1, 20, 20, 2],
            3: [20],
            4: [20],
            20: [3, 10, 10, 4],
        }

    def hourglass_plus_edge_fixture(self):
        return (
            {
                1: [10],
                10: wrench.HourglassPorts(
                    {"top": 1, "bot": 20},
                    slot_pattern=("ordinary", "hourglass", "hourglass", "ordinary"),
                ),
                20: wrench.HourglassPorts(
                    {"top": 10, "bot": 2},
                    slot_pattern=("ordinary", "hourglass", "hourglass", "ordinary"),
                ),
                2: [20],
            },
            [{"white": 10, "black": 20}],
        )

    def test_two_edge_lens_becomes_hourglass_with_coefficient_two(self):
        adj = self.lens_fixture()
        matches = wrench.detect_double_edge_skein_moves(adj, [], self.colors)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["kind"], "double_edge")
        self.assertEqual(matches[0]["coefficient_multiplier"], 2)

        reduced_adj, reduced_hgs = wrench.apply_double_edge_skein_move(
            adj, [], matches[0]
        )
        self.assertIsInstance(reduced_adj[10], wrench.HourglassPorts)
        self.assertIsInstance(reduced_adj[20], wrench.HourglassPorts)
        self.assertEqual(len(reduced_hgs), 1)
        self.assertNotIn(20, reduced_adj[10].values())
        self.assertNotIn(10, reduced_adj[20].values())

    def test_nonadjacent_parallel_half_edges_are_not_a_lens(self):
        adj = self.lens_fixture()
        adj[10] = [1, 20, 2, 20]
        adj[20] = [3, 10, 4, 10]
        self.assertEqual(
            wrench.detect_double_edge_skein_moves(adj, [], self.colors),
            [],
        )

    def test_hourglass_plus_edge_collapses_with_coefficient_three(self):
        adj, hourglasses = self.hourglass_plus_edge_fixture()
        matches = wrench.detect_double_edge_skein_moves(
            adj, hourglasses, self.colors
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["kind"], "hourglass_plus_edge")
        self.assertEqual(matches[0]["coefficient_multiplier"], 3)

        reduced_adj, reduced_hgs = wrench.apply_double_edge_skein_move(
            adj, hourglasses, matches[0]
        )
        self.assertEqual(reduced_adj, {1: [2], 2: [1]})
        self.assertEqual(reduced_hgs, [])

    def test_history_replay_uses_the_same_reduction(self):
        x_adj, x_hgs = self.hourglass_plus_edge_fixture()
        match = wrench.detect_double_edge_skein_moves(
            x_adj, x_hgs, self.colors
        )[0]
        w_adj = {101: [102], 102: [101]}
        initial = {
            "x_adj": copy.deepcopy(x_adj),
            "x_remaining": copy.deepcopy(x_hgs),
            "w_adj": copy.deepcopy(w_adj),
            "w_remaining": [],
            "coeff": 1,
            "history": [],
        }
        child = wrench.expand_pair_term_by_double_edge_skein(
            initial, "X", match
        )[0]
        self.assertEqual(child["coeff"], 3)
        self.assertEqual(child["history"][0]["phase"], "double_edge_skein")

        replay_x, replay_xh, replay_w, replay_wh = wrench.replay_pair_history(
            x_adj,
            x_hgs,
            w_adj,
            [],
            child["history"],
        )
        self.assertEqual(replay_x, child["x_adj"])
        self.assertEqual(replay_xh, child["x_remaining"])
        self.assertEqual(replay_w, child["w_adj"])
        self.assertEqual(replay_wh, child["w_remaining"])


if __name__ == "__main__":
    unittest.main()
