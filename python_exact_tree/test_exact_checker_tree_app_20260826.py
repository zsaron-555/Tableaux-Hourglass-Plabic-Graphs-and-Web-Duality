#!/usr/bin/env python3
"""Regression checks for the Python exact pairing-tree inspector."""

from __future__ import annotations

import unittest

import exact_checker_tree_app_20260826 as app


class ExactCheckerTreeAppTests(unittest.TestCase):
    def tree(self, w: str, x: str):
        return app.compute_tree(str(app.resolve_graph(w)), str(app.resolve_graph(x)))

    def test_wrench_highlights_complete_local_piece(self) -> None:
        tree = self.tree(
            "23563_1234111222333444.json",
            "00210_1111223344234234.json",
        )
        root = tree["nodes"][0]
        outgoing = root["outgoing"]
        web = root[outgoing["side"].lower()]
        vertices, ordinary_edges, bundles = app.selected_relation_parts(web, outgoing)
        self.assertEqual(outgoing["relationFamily"], "wrench")
        self.assertEqual(len(vertices), 2)
        self.assertEqual(len(ordinary_edges), 4)
        self.assertEqual(len(bundles), 1)
        self.assertEqual(tree["result"]["value"], 0)

    def test_benzene_words_require_explicit_presentation_selection(self) -> None:
        word = "1111223223443344"
        payload = app.benzene_presentation_options(word)
        self.assertTrue(payload["requiresSelection"])
        self.assertEqual(payload["selected"], "")
        self.assertEqual(
            [option["representation"] for option in payload["options"]],
            ["top", "bottom"],
        )
        with self.assertRaisesRegex(ValueError, "Select its exact top, middle, or bottom presentation"):
            app.resolve_selected_graph(word, "", "W")
        selected_paths = [
            app.resolve_selected_graph(word, option["value"], "X")
            for option in payload["options"]
        ]
        self.assertEqual(len(set(selected_paths)), 2)

    def test_double_trident_highlights_all_seven_edges_and_uses_gppss(self) -> None:
        tree = self.tree(
            "21634_1231142132233444.json",
            "02391_1112312423434234.json",
        )
        root = tree["nodes"][0]
        outgoing = root["outgoing"]
        web = root[outgoing["side"].lower()]
        vertices, ordinary_edges, bundles = app.selected_relation_parts(web, outgoing)
        self.assertEqual(outgoing["relationFamily"], "double_trident")
        self.assertEqual(len(vertices), 2)
        self.assertEqual(len(ordinary_edges), 7)
        self.assertFalse(bundles)
        self.assertIn("GPPSS", outgoing["certificateConvention"])
        self.assertEqual(
            [(record["color"], record["permutationSign"]) for record in outgoing["tagging"]],
            [("white", 1), ("black", -1)],
        )
        self.assertEqual(tree["result"]["value"], -1)
        self.assertEqual(len(root["children"]), 6)
        by_id = {node["id"]: node for node in tree["nodes"]}
        for child_id in root["children"]:
            child = by_id[child_id]
            side = child["incoming"]["side"].lower()
            branch_vertices, branch_edges, branch_bundles = app.resulting_branch_parts(
                root[side], child[side]
            )
            self.assertEqual(len(branch_vertices), 6)
            self.assertEqual(len(branch_edges), 3)
            self.assertFalse(branch_bundles)

    def test_wrench_example_contains_two_simultaneously_surviving_branches(self) -> None:
        tree = self.tree(
            "23563_1234111222333444.json",
            "00001_1111222233334444.json",
        )
        by_id = {node["id"]: node for node in tree["nodes"]}
        parent = by_id["N001"]
        surviving = [
            by_id[child_id]
            for child_id in parent["children"]
            if by_id[child_id]["status"] == "active"
        ]
        self.assertEqual([node["incoming"]["branch"] for node in surviving], ["crossing", "parallel"])
        for child in surviving:
            side = child["incoming"]["side"].lower()
            _vertices, branch_edges, branch_bundles = app.resulting_branch_parts(
                parent[side], child[side]
            )
            self.assertEqual(len(branch_edges), 2)
            self.assertFalse(branch_bundles)
            card = app.render_node(child, parent)
            self.assertIn("resulting branch edges", card)
            self.assertIn(app.BRANCH_BLUE, card)

    def test_deep_demo_and_convention_boundary_are_rendered(self) -> None:
        tree = self.tree(
            "23563_1234111222333444.json",
            "00001_1111222233334444.json",
        )
        self.assertEqual(max(node["depth"] for node in tree["nodes"]), 6)
        output = app.page(
            tree,
            "23563_1234111222333444.json",
            "00001_1111222233334444.json",
        )
        self.assertIn("manual mode keeps the latest three picture levels", output)
        self.assertIn("automatically show every branch picture", output)
        self.assertIn("Back to previous layer", output)
        self.assertIn("back-local", output)
        self.assertIn("Branch pairing ledger", output)
        self.assertIn("Show branch pictures", output)
        self.assertIn(
            "The value and every displayed branch come from the same exact scheduler result",
            output,
        )
        self.assertIn('<strong id="final-value">+0</strong>', output)
        self.assertIn('class=\"summary-svg\"', output)
        self.assertIn("summary-edge", output)
        self.assertIn("summary-node-target", output)
        self.assertIn("Click any labeled node", output)
        self.assertIn("function bindSummaryNodes()", output)
        self.assertIn("focusBranch(target.dataset.node)", output)
        self.assertIn("Local tag transport and certified skein coefficients use GPPSS, not FLL", output)
        self.assertIn("FLL is used only at terminal conversion", output)
        self.assertIn(app.GRAPH_DATA_DOWNLOAD_URL, output)
        self.assertNotIn(str(app.catalogue_graph_dir()), output)
        self.assertIn('--project-root "/path/to/folder-containing-4x4_All_graph_data"', output)

    def test_tree_and_wrench_entry_points_select_the_requested_initial_view(self) -> None:
        tree = self.tree(
            "23563_1234111222333444.json",
            "00210_1111223344234234.json",
        )
        tree_output = app.page(
            tree,
            "23563_1234111222333444.json",
            "00210_1111223344234234.json",
            initial_view="summary",
        )
        wrench_output = app.page(
            tree,
            "23563_1234111222333444.json",
            "00210_1111223344234234.json",
            initial_view="picture",
        )
        self.assertIn('name="view" value="summary"', tree_output)
        self.assertIn("<h1>Pairing Explorer</h1>", tree_output)
        self.assertIn("Open Web Explorer", tree_output)
        self.assertIn("const initialView=\"summary\"", tree_output)
        self.assertIn("if(initialView==='summary')showSummary()", tree_output)
        self.assertIn('name="view" value="picture"', wrench_output)
        self.assertIn("<h1>Pairing Explorer</h1>", wrench_output)
        with self.assertRaisesRegex(ValueError, "Unknown initial view"):
            app.page(tree, "W", "X", initial_view="legacy")

    def test_project_root_accepts_parent_or_extracted_graph_folder(self) -> None:
        original = app.PROJECT_ROOT
        extracted = app.catalogue_graph_dir()
        try:
            app.configure_project_root(extracted.parent)
            self.assertEqual(app.catalogue_graph_dir(), extracted)
            app.configure_project_root(extracted)
            self.assertEqual(app.catalogue_graph_dir(), extracted)
        finally:
            app.configure_project_root(original)

    def test_missing_data_page_contains_download_and_launch_instructions(self) -> None:
        output = app.error_page("graph data missing")
        self.assertIn(app.GRAPH_DATA_DOWNLOAD_URL, output)
        self.assertIn("--project-root", output)


if __name__ == "__main__":
    unittest.main()
