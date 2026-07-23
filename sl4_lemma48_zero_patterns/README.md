These JSON files record the GL4 specialization of the generalized Lemma 4.8
zero-discharge rule from `Lemma4.8_SL4.pdf`.

The Lemma 4.8 picture has a variable-length cyclic boundary interval, so the
detector is programmatic rather than a fixed node-for-node snippet matcher.
The JSON catalog keeps the rule source, matching parameters, and the local
coloring contradiction visible for collaborators.

Current implemented criterion:

- On a cyclic interval `v1, ..., v_a, v_{a+1}, v_{a+2}`, W has
  `v_{a+1}` and `v_{a+2}` attached to the same internal white vertex.
- W also has a visible middle fan: one internal white vertex attached to at
  least two boundary labels among `v2, ..., v_a`.
- X has `v1`, `v_{a+1}`, and `v_{a+2}` in the same underlying component,
  counting hourglass pairs as connections.

When all three conditions hold, the pairing branch is discharged with value 0.
