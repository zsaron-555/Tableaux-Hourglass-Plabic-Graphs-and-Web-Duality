# Square-move presentation catalogue

The web explorer treats a presentation as an exact embedded, boundary-labelled
colored ribbon graph. A square-move catalogue must therefore preserve more than
abstract adjacency: it must also transport the cyclic order of half-edges at
every affected vertex and retain the boundary labels.

## Safe generation workflow

1. Encode each allowed local square move as a reversible replacement rule with
   explicit black/white corners, ordinary/hourglass sides, external ports, and
   half-edge transport.
2. Apply one rule to an exact JSON presentation.
3. Rebuild and validate `edges`, `hourglasses`,
   `effective_rotation_system`, `strand_edges_for_trips`, and drawing routes.
4. Canonicalize the result as a boundary-fixed colored ribbon graph.
5. Explore the finite move class with a visited-state set, so reversing a move
   cannot create an infinite cycle.
6. Store each new exact presentation as a JSON file and record its source,
   move path, and word in `square_move_presentations/manifest.json`.

The present code certifies two restricted, monotone square reductions used by
the pairing and surgery engines. A scan of the 24,024 catalogue JSONs and the
704 generated benzene-move JSONs found no source presentation to which either
restricted rule applies. Those rules therefore certify some surgery outputs,
but they do not yet produce extra selectable square-move presentations for the
existing catalogue.

We should not generate a purported complete square-move folder until the other
GPPSS local cases have been translated into the same explicit port and rotation
conventions. Once those rules are supplied, the six-step workflow above can
generate the folder without changing the explorer's data model.
