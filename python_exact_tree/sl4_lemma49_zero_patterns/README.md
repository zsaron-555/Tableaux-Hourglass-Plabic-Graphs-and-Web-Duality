# SL4 Lemma 4.9 zero-pair patterns

## Additional zero-pairing drawings

The six `additional_zero_*.json` files follow the drawings in
`Additional Zero Pairings.pdf` literally:

- The edges listed in `interpretation.blue_edge_ids_by_side` are the blue
  edges in the source drawing. Exactly one of those edges is an hourglass;
  all remaining blue edges are ordinary.
- Every edge listed in `interpretation.boundary_leg_edge_ids_by_side` is an
  ordinary edge ending at a black `disk_boundary` vertex. Such a leg may not
  be matched to an internal black vertex.
- Additional edges or hourglasses incident to matched local vertices are not
  restricted unless the pattern says otherwise.
- Disk rotations, reflections, and the allowed W/X side swap are handled by
  the matcher; they are not duplicated as separate JSON files.

Case 6 is explicitly described in the source as already covered by the case 4
generalization. Its JSON therefore records the same local topology and marks
the alias in `interpretation.alias_of`.

This directory transcribes the blue-boxed candidate SL4 analogues in
`Lem 4.9 abefghi (1).pdf`.

The catalogue contains cases `a`, `b`, `d`, `e`, `f`, `g`, `h`, and `i`, the
user-supplied `extra_outer_pair_four_fan` pattern, and six source-traceable
generalized cases from `Additional Zero Pairings.pdf`. Each case is a
**paired** local condition: both its `W` and `X` windows must match before the
branch may be discharged.

## Matcher contract

1. Match the listed disk-boundary nodes to one consecutive cyclic boundary
   interval. Cyclic shifts are allowed.
2. Preserve black/white vertex colors, ordinary edges, multiplicity-two
   hourglasses, and the cyclic order induced by the stored embedding.
3. `window_port` nodes are half-edges leaving the local window. They match
   arbitrary continuation outside the window, not disk-boundary vertices.
4. Reflections and swapping the two paired webs are allowed by the manifest.
5. Entries in `crossings` are geometric strand crossings, not vertices.
6. Only after both sides match may the proof branch be discharged with
   `pairing_value = 0` and the recorded `reason`.

The generalized cases from `Additional Zero Pairings.pdf` also use
`ordinary_or_hourglass` for a blue edge that may be replaced by an hourglass,
`exact_edge_kind_count` when exactly one edge in a displayed family must be
an hourglass, and `boundary_offsets` for a shared variable cyclic gap on both
sides. These alternatives are matched directly from graph data.

Run `python3 validate_sl4_lemma49_patterns.py` from the project directory to
check the catalogue before using it.

