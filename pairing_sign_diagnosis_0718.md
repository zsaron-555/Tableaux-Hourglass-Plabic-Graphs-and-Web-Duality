# Pairing symmetry sign diagnosis (2026-07-18)

## Defects found

1. The Figure 43 vertical term's paper coefficient and its tag transport were
   represented by one number. The paper coefficient remains `-2`; translating
   the pictured tagged term into the engine's stored cyclic convention has a
   separate tag-transport multiplier `-1`.
2. Terminal Plucker orientation was recomputed from flattened adjacency. That
   graph no longer contains every tag motion made by earlier relations. The
   terminal conversion sign must instead be accumulated from relation history.
3. Every white-black antisymmetrizer application transports the terminal tag
   convention by `-1`. Figure 43 contributes its recorded transport multiplier.
   Moves on the colored (non-source) side do not affect the source orientation.

## Implementation

- Figure 43 history now stores `paper_coefficient_multiplier`,
  `tag_transport_multiplier`, and the effective `coefficient_multiplier`.
- Antisymmetrizer history stores `tag_transport_multiplier = -1`.
- Terminal coloring uses `relation_history_orientation_sign(history, side)` and
  applies this conversion exactly once to the unsigned consistent-labeling count.
- The explorer displays paper, tag-transport, and effective multipliers separately.

## Verification

- Four focused regression suites pass.
- The hand-computed control gives `0` in both orders.
- Eighteen nonzero stress pairs give `1` in both orders. Two slow reverse orders
  required isolated 300/600-second caps, but both eventually completed with `1`.
- No completed post-fix audit pair has `<W,X> != <X,W>`.

This is strong regression evidence for the repaired convention. It is not a
formal proof that every possible relation path is sign-correct; future batch
audits should continue to record both orders.
