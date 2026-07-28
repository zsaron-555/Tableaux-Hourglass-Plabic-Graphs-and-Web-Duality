These JSON files record the corrected GL4 specialization of generalized
Lemma 4.8 shown in `IMG_5961.heic`.

The earlier detector used a variable boundary window and an underlying
connected-component condition on X. That criterion was too broad. The
corrected detector requires the exact paired local subgraphs on the same five
consecutive boundary labels `v1,...,v5`:

- W has a black hub with ordinary edges to a left white vertex and a
  three-spoke white fan, plus an hourglass to a right white vertex.
- The left white vertex meets `v1`, the fan meets `v2,v3,v4`, and the right
  white vertex meets `v5`.
- X has the alternating chain
  `xw1 ==hourglass== xb1 -- xw2 ==hourglass== xb2 -- xw3`.
  Its white vertices meet boundary labels `(v1,v2)`, `v3`, and `(v4,v5)`,
  respectively.

Only the displayed local incidences are required; edges leaving the local
window are unrestricted. The matcher tests this five-label pattern starting
at every boundary label in both cyclic directions, so all disk rotations and
reflections are included.
