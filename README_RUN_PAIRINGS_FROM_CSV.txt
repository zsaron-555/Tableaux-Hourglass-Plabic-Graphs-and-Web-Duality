RUN SL4 PAIRINGS FROM A CSV OR TSV
=================================

Put these files in the same repository folder:

  run_pairings_from_csv.py
  compute_pairing_values_optimized_20260726.py
  Wrench_or_Skein_optimized_20260726.py
  ribbon_cache_optimized_20260726.py
  web_relation_rules_optimized_20260726.py
  wrench_web_app_0714.py
  Wrench_or_Skein_0714.py
  web_relation_rules_0714_2.py

The graph-data folder must also be available somewhere under Desktop,
Documents, Downloads, or the repository folder:

  4x4_All_graph_data

Your input may be a .csv or .tsv. It needs a header and one W column plus one
X column. For example:

  w_word,x_word
  1111222233334444,1123213441232344
  1112122323343444,1211322143324434

MAC
---

1. Open Terminal.
2. Type "cd " (including the space), drag the repository folder into Terminal,
   and press Return.
3. Run:

   python3 run_pairings_from_csv.py "/path/to/my_pairs.csv" --workers 4 --keep-awake

WINDOWS
-------

1. Open the repository folder in File Explorer.
2. Click the address bar, type cmd, and press Enter.
3. Run:

   py run_pairings_from_csv.py "C:\path\to\my_pairs.csv" --workers 4

OUTPUT
------

The program creates these files beside the input:

  my_pairs_pairing_values.tsv       final values and statuses
  my_pairs_pairing_values.log       progress
  my_pairs_pairing_values_tasks.tsv normalized input
  my_pairs_pairing_values_timeout_states/
                                     final branch-state JSONs for timeouts

The output is checkpointed after every pair. Running the same command again
resumes and skips pairs already present in the result TSV.

DIVIDE ONE INPUT AMONG SEVERAL COMPUTERS
----------------------------------------

For four computers, all use the same input file and choose a different index:

  Computer 1: --shard-index 1 --shard-count 4
  Computer 2: --shard-index 2 --shard-count 4
  Computer 3: --shard-index 3 --shard-count 4
  Computer 4: --shard-index 4 --shard-count 4

Each computer writes a separately named shard result. Concatenate the shard
TSVs once every run has finished.

OPTIONS
-------

  --workers 4             number of parallel processes
  --timeout-minutes 60    timeout for one pair
  --timeout-minutes 0     no per-pair timeout
  --keep-awake            keep a Mac awake while running
  --dry-run               validate and split the input without computing

Use fewer workers if the computer becomes unresponsive or memory pressure is
high. Four workers is a conservative default.
