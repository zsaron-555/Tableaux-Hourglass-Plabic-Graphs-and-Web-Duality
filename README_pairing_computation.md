# Computing SL4 Pairing Values

The batch entry point is:

`compute_pairing_values_optimized_20260726.py`

It uses the cached ribbon-state engine, canonicalizes intermediate webs, reuses
reductions for repeated `X` webs, and writes each finished pairing immediately
to a checkpoint TSV. Rerunning the same command resumes from that TSV.

## Required data

Keep these inputs together in one data folder:

- `4x4_All_graph_data/` (or `hourglass_disk_4x4_all_graph_data/`)
- `lemma46_survivors.csv`

The graph-data folder is large and is not stored in GitHub. Download it
separately, then pass its containing folder with `--project-root`.

## Compute the full survivor-pair list

Open Terminal in the GitHub repository and run:

```bash
python3 compute_pairing_values_optimized_20260726.py \
  --project-root "/path/to/folder-containing-graph-data" \
  --out "All_Pairings.tsv" \
  --log "All_Pairings.log" \
  --workers 12 \
  --task-timeout 600 \
  --task-order by-x-cache
```

On macOS, prefix the command with `caffeinate -dimsu` to keep the laptop awake:

```bash
caffeinate -dimsu python3 compute_pairing_values_optimized_20260726.py \
  --project-root "/path/to/folder-containing-graph-data" \
  --out "All_Pairings.tsv" \
  --log "All_Pairings.log" \
  --workers 12 \
  --task-timeout 600 \
  --task-order by-x-cache
```

## Compute an explicit list of pairs

Supply a tab-separated task file containing the columns `w_idx`, `w_word`, and
`x_word`:

```bash
python3 compute_pairing_values_optimized_20260726.py \
  --project-root "/path/to/folder-containing-graph-data" \
  --task-file "/path/to/pairs.tsv" \
  --out "pairing_values.tsv" \
  --log "pairing_values.log" \
  --workers 12 \
  --task-timeout 600 \
  --task-order by-x-cache
```

Use fewer workers if the computer becomes unresponsive. The output TSV is a
checkpoint, so the same command can be restarted without recomputing completed
pairs.

