Portable wrench pairing webpage
================================

Put these files/folders in the same folder:

  wrench_web_app.py
  Wrench_or_Skein.py
  hourglass_disk_4x4_all_graph_data/
  hourglass_disk_4x4_promotion_reps_graph_data/
  hourglass_disk_4x4_transpose_words_graph_data/

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
