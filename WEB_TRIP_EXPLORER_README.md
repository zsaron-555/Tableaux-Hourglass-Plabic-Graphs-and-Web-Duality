# Trips & promotion — offline Gr(4,16) explorer

## Use it

1. Open `web_trip_explorer.html` in a desktop browser. No server, install, build step, or internet connection is required. An included example appears immediately.
2. Click **Choose JSON folder** and select your `jsons` directory. **Choose files** is an alternative for selecting individual JSONs.
3. Select a JSON in the file bar. Select a starting boundary vertex from the dropdown, click its label or point in the web, or use the previous/next boundary buttons.
4. The three trips appear in purple, orange, and green. Toggle their checkboxes to isolate paths. **Trace trips** draws the paths in traversal order. Zoom controls and **Fit** adjust the drawing.
5. The original tableau T is on the left of the promotion panel. For starting boundary b, the larger board shows P^(b−1)(T), the tableau to promote. **Play**, the step arrows, and the slider show the hole and jeu de taquin slides. The colored entries cross rows 2→1, 3→2, and 4→3.
6. Each color card compares trip_i(b) with prom_i(b). If the crossing entry is a_i, the promotion endpoint is a_i+b−1 modulo 16, taking values in 1,…,16. A residue of zero is displayed as 16.

**SVG ↓** exports the current web and visible trips as a standalone vector drawing. **Download computed check** in the expandable section exports all three permutations, all 48 comparisons, and the selected trip/promotion traces as JSON. Selecting files never uploads them or edits the originals.

## Add it to your GitHub repository

Copy `web_trip_explorer.html` into the repository and commit it alongside your JSON data. Readers can download the repository, extract the ZIP, and open the HTML. They then choose the local `jsons` folder using the page's folder picker. The HTML can be moved or renamed; it has no dependencies or hardcoded local filesystem paths. It also works as a static GitHub Pages page while still reading files chosen on the visitor's device.

The HTML is the only required application file. The regression test and this README are optional companion files. No hosting account or Sites deployment is involved.

## Supported data and conventions

The explorer supports the two schemas used by the audited octagon data:

- `hourglass_plabic_graph_v1`: nodes/edges, `effective_rotation_system`, and a row word.
- `sl4-surgery-ribbon-graph-v1`: nodes/edges, edge multiplicities, and `rotation_ccw`.

It requires 16 black boundary vertices, labeled 1,…,16, with weighted degree one; bipartite edges; and internal weighted degree four. Coordinates `x` and `y` and a cyclic rotation system must be present. Raw ordinary-edge parallel pairs and open-port construction diagrams are deliberately rejected rather than treated as hourglass webs. This is a graph/tableau correspondence viewer, not a full-reducedness or tensor-identity prover.

At a white vertex a trip takes the i-th left; at a black vertex the i-th right. The half-twist is reconstructed from the abstract edge block and multiplicity: the same local strand occurrence is used at both endpoints. Redundant original strand-ID exports are not used for transport. Endpoint-order disagreements are reported in the expandable conventions section. Drawings use the saved coordinates; turns use the saved cyclic orders, not screen angles.

Row-word priority is `word`, `metadata.tableau_word`, `metadata.target`, `metadata.word`, then an `original_WORD.json` filename. The six known `orbit_I_STAGE.json` families have a fallback mapping: W/exposed use the initial word; R/spliced/contracted use the correction word; orbit 1 Q/unzipped use Q. This mapping is explicitly labeled in the interface. An unknown filename without a usable word asks for a manual row word. A manual override is kept for that file during the current session. Mismatches are displayed rather than suppressed.

Reference: Gaetz, Pechenik, Pfannerer, Striker, and Swanson, [Rotation-invariant web bases from hourglass plabic graphs](https://arxiv.org/pdf/2306.12501), §3.1 and Definitions 3.4, 4.6, 4.12.

## Optional verification

The application needs no Node.js. Developers who have Node.js can run:

```
node test_web_trip_explorer.cjs
node test_web_trip_explorer.cjs "path/to/jsons"
```

The script extracts and tests the mathematical code directly from the HTML. It checks the paper's Figure 1 benchmark, independently computes promotion through balance points, verifies promotion rotation and inverse identities, and tests invalid words and a deliberately incorrect tableau. The second command also verifies every supported web in a JSON folder.

To compare against the earlier Python audit, provide its result file as a third command-line argument:

```
node test_web_trip_explorer.cjs "path/to/jsons" "path/to/web_audit.json"
```

Validation completed against all 45 supplied JSONs: all 2,160 trip endpoints and 2,160 promotion endpoints agree with the Python audit. All 45 files were also loaded and rendered in the browser. Folder and multiple-file selection, missing words, invalid JSON, wrong-tableau mismatches, boundary wraparound, keyboard selection, playback/pause, color toggles, and both exports were checked. The application has no external scripts, stylesheets, fonts, analytics, or runtime network requests; the reference paper link opens only when clicked.
