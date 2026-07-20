# SL4 Lemma 4.9 zero-pair patterns

This directory transcribes the blue-boxed candidate SL4 analogues in
`Lem 4.9 abefghi (1).pdf`.

The catalogue contains cases `a`, `b`, `e`, `f`, `g`, `h`, and `i`, plus the
user-supplied `extra_outer_pair_four_fan` pattern. Each case is a **paired**
local condition: both its `W` and `X` windows must match before the branch may
be discharged.

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

Run `python3 validate_sl4_lemma49_patterns.py` from the project directory to
check the catalogue before using it.
