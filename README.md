# Tableaux-Hourglass-Plabic-Graphs-and-Web-Duality
UMN Algebra and combinatorics REU

Computational tools for the REU project on self-dual web bases for the Grassmannian Gr(4,16), summer 2026 (Advisor: Prof. Musiker)

## Run the local Wrench Pairing Explorer

Download or clone the entire repository. Keep these relation assets beside the
Python files:

- `sl4_lemma48_zero_patterns/`
- `sl4_lemma49_zero_patterns/`
- `bcgmmw_lemma49_exemplars_0714.json`

The large graph-data folder does not need to be stored at a fixed path. Extract
`4x4_All_graph_data.zip`, then either put the extracted folder beside the
repository or pass the folder containing it with `--project-root`.

macOS or Linux:

```bash
cd /path/to/Tableaux-Hourglass-Plabic-Graphs-and-Web-Duality
python3 wrench_web_app_0714.py --project-root "/path/to/folder/containing/4x4_All_graph_data"
```

Windows:

```powershell
cd C:\path\to\Tableaux-Hourglass-Plabic-Graphs-and-Web-Duality
py wrench_web_app_0714.py --project-root "C:\path\to\folder\containing\4x4_All_graph_data"
```

Then open <http://127.0.0.1:8765/>.

No source-code path needs to be edited. The app resolves its relation files
relative to each person's downloaded repository. `--project-root` can also be
replaced by the `PROBLEM3_ROOT` environment variable, and `PROBLEM3_APP_DIR`
may be used when another script imports the app from this repository.
