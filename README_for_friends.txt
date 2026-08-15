Portable wrench pairing webpage
================================

Graph-data download
-------------------

Download this release file:

  4x4_All_graph_data_260815.zip

  https://github.com/zsaron-555/Tableaux-Hourglass-Plabic-Graphs-and-Web-Duality/releases/download/sl4-web-data-v1/4x4_All_graph_data_260815.zip

The web explorer can read this ZIP directly. Open web_explorer_v4.html, click
"Choose downloaded ZIP", and select 4x4_All_graph_data_260815.zip. You do not
need to extract or rename the ZIP. If you prefer to extract it, click "Choose
extracted folder" and select the folder named 4x4_All_graph_data.

The ZIP includes the 24,024 catalogue JSON files, the additional benzene-move
presentations, and the presentation-aware benzene-surgery lookup. When a web
has more than one presentation, use the presentation selector before looking
at its surgery channels. The surgery panel is recomputed from the exact JSON
currently displayed.

The explorer can be opened from the local wrench webpage, or served directly
from the folder containing web_explorer_v4.html and the graph-data ZIP.

Wrench pairing webpage
----------------------

Put these files/folders in the same folder:

  wrench_web_app.py
  Wrench_or_Skein.py
  hourglass_disk_4x4_all_graph_data/
  hourglass_disk_4x4_promotion_reps_graph_data/
  hourglass_disk_4x4_transpose_words_graph_data/

No absolute path needs to be edited. Keep the folder named
hourglass_disk_4x4_all_graph_data/ next to wrench_web_app.py.
This is a folder, not one file. It contains the 24,024 JSON files plus
all_4x4_words.tsv and graph_data_diagnostics.jsonl.

The PNG folders are optional. The webpage computes from the JSON folders.

To run the webpage:

  python3 wrench_web_app.py --port 8765

Then open this link on the same computer:

  http://127.0.0.1:8765/

The page uses a compact step summary by default so it loads quickly. Check
"show full step pictures" before running if you want the full visual proof
sequence.

The main form asks for W first and X second. They do not need to be transpose
pairs. You can enter an index, a Yamanouchi word, or a JSON filename for each
side. If hourglass_disk_4x4_all_graph_data/ is present, manual W/X indices use
the full 24,024-word list. There is also a shortcut section if you want to use
one 1,522-orbit representative and its transpose automatically.

If the JSON folders are somewhere else, run:

  python3 wrench_web_app.py --port 8765 --project-root "/path/to/folder/with/json/folders"

You can also set the environment variable PROBLEM3_ROOT to that folder.
