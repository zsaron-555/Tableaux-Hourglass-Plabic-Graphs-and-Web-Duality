OCTAGON SURGERY FOR THE COMMON C BASIS

Read Octagon_surgery_common_C.pdf (9 pages) first.

The diagrams are positive graph-matching results for the six representatives.
This is a new geometric correction prescription, not an invariant-preserving
skein relation. In particular the operation includes replacing each doubled
ordinary pair by an hourglass. The signs of C are taken from the original
booklet; orbits 2 and 5 have plus signs on the unsigned correction diagram.

Verification:
  python3 verify_surgeries.py
Standard library only. It enumerates the complete six square orbits, replays
the square paths, checks all 12 exposed-octagon matches with cyclic order,
and verifies the orbit 1 unzip. No random numerical test is used.

LaTeX:
  pdflatex Octagon_surgery_common_C.tex
  pdflatex Octagon_surgery_common_C.tex
The figures/ directory includes vector PDFs and PNGs.

JSONs:
  original_WORD.json: unmodified project JSON with full strand data.
  orbit_I_W.json / _R.json / orbit_1_Q.json: display versions of those graphs.
  orbit_I_exposed.json: square-moved presentation, highlighted octagon.
  orbit_I_spliced.json: after deleting the face and bundling the new pairs.
  orbit_I_contracted.json: after four bivalent 2+2 contractions.
  orbit_1_unzipped.json: second-stage output of the chain.
Generated graphs use schema sl4-surgery-ribbon-graph-v1. rotation_ccw stores
one neighbor per abstract edge; an hourglass neighbor occurs once, with
edge multiplicity 2. Figures use stored coordinates, not a reconstruction
of the topology from screen angles. The splice and unzip conventions are
in replay/surgery_core.py and in the PDF.

verification.json records the exact paths, operations, and graph isomorphisms.
replay/ contains the necessary exact square-move and graph algorithms.
build_figures.py is the original workspace figure-generation driver; it uses
the earlier workspace directory structure. For portable figure regeneration,
run render_jsons.py (requires numpy and matplotlib).

Source mathematical context: Gaetz--Pechenik--Pfannerer--Striker--Swanson,
arXiv:2306.12501, Figures 2 and 9, Section 6.3. The octagon correction
surgeries and the finite matching checks are the new observations here.
