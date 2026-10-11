---
name: oa3-ablation
description: Run the OA-3 parameter-sensitivity (ablation) experiment on OA-SLAM-YOLOv8n end to end — expose the association parameters, smoke-test, run the interleaved cell matrix with repeated runs, evaluate ATE/RPE with evo, and produce the report for the IJRA revision (Reviewers A and D). Use when the user asks to run, resume, or report OA-3.
---

# OA-3 ablation agent procedure

You are operating the `oa3-agent` package (this folder). The deterministic work is done by scripts;
your job is to drive them in the right order, check every gate, and never invent a number.
Talk to the user in **Indonesian** (the manuscript and the reports stay in English).

## Ground rules (never break)
1. **Do not change** the detector, its weights, the confidence threshold used by the manuscript (0.5), the ORB
   settings, the camera YAML files or the datasets. OA-3 varies only the parameters listed in `oa3_config.yaml`.
2. **No TensorRT**, no other GPU/CPU-heavy job on the machine while runs are in progress, **never two runs in
   parallel** (OA-SLAM replays at sensor rate; concurrency changes the results).
3. **Ask before** editing any file inside the OA-SLAM fork, rebuilding it, deleting results, or starting the
   full matrix. Show the diff (`tools/patch_params.py --diff`) before `--apply`.
4. **Never fabricate defaults.** The defaults of the fork come from `tools/patch_params.py --check`
   (captured from the source) or from the user; a placeholder in the config is a blocking problem.
5. **Never edit files under `results_root`** by hand. Re-run the scripts instead (they are resumable).
6. Report what the scripts report. Interpretation beyond `OA3_report.md` section 6 is the user's decision.

## Step 0 — orientation (2 min)
- `cat README.md`, `cat oa3_config.yaml` (create it from `oa3/config_example.yaml` if missing).
- Confirm with the user: path of the fork (`project.oa_slam_root`), that it is **built** (`bin/oa-slam` exists),
  the sequence folders, the detection JSON files used for the manuscript, and the value of `reloc_mode`
  used in the manuscript. Fill the config accordingly.
- Platform: prefer the lab workstation over the Jetson for OA-3 (accuracy does not depend on the platform;
  OA-1 is the Jetson experiment). Record which machine is used; `runner` writes `platform.json`.

## Step 1 — preflight
```
python -m oa3.preflight --config oa3_config.yaml
```
Fix every `PROBLEM` line. Typical: wrong paths, detection JSON `file_name` not matching `rgb.txt`,
placeholder defaults, `include/oa3_params.h` missing (→ Step 2).

## Step 2 — parameter exposure (once per fork)
```
python tools/patch_params.py --root <oa_slam_root> --check
```
- Every anchor must be `found` or `already applied`. The table also prints the **detected defaults**
  (`OA_DET_SCORE`, `OA_IOU2D`, `OA_IOU3D`, `OA_TIME_DIFF`, `OA_NB_MATCH`, `OA_MIN_OBS`, `OA_MAP_OBS`):
  copy them into `ablation.default` of `oa3_config.yaml` and derive the cells from them
  (P1: both IoU gates −50 % / +0.2; P2: min_obs ×½ / ×2; keep the other variables at default).
- If an anchor is `NOT FOUND` or `AMBIGUOUS`, the fork differs from upstream there: open `src/Tracking.cc`,
  locate the equivalent statement (search `MIN_2D_IOU_THRESH`, `MIN_3D_IOU_THRESH`, `TIME_DIFF_THRESH`,
  `THRESHOLD_NB_MATCH`, `GetNbObservations() >`, `InsertInMap(`), propose a manual edit that keeps the
  exact log formats (`EFFECTIVE k=v`, `ASSOC <frame> matched|new <id>`, `LANDMARK_NEW <frame> <id> <cat>`,
  `LOST <frame>`, `RELOC <frame> <ok> <ms>`, `FRAME <i> <ms>`), show it, and apply only after approval.
- Show `--diff` to the user, get approval, then `--apply`, then rebuild the fork the way the user builds it
  (usually `cd build && cmake .. && make -j$(nproc)`; on the Jetson use `-j4` or less). Verify that the binary
  timestamp changed. `--revert` restores the originals if anything goes wrong.

## Step 3 — smoke test (mandatory before the matrix)
```
python -m oa3.runner --config oa3_config.yaml --only-seqs <control_sequence> --only-cells default --runs 1
python -m oa3.evaluate --config oa3_config.yaml
```
Check in `<results_root>/<control>/default/run01/`:
- `run.log` starts with the 7 `EFFECTIVE` lines and their values equal `ablation.default`;
- `FRAME`, `Nb Map Objects`, `mean tracking time` lines are present; `camera_poses_*_tum.txt` exists;
- `meta.json`: `status: ok`, `coverage` ≥ 0.9, `effective_mismatch: {}`;
- `eval.json`: the ATE of the control sequence is in the range of the repeated-run campaign for that
  sequence (bonn_crowd: ≈ 0.06–0.07 m in the 5-run campaign). If it is far off, **stop** and report: the
  evaluation identity (trajectory file, alignment, identity-row dropping) or the configuration differs from
  the campaign and must be settled with the user before any matrix run.
Then one run of `P1_tight` on the same sequence: the `EFFECTIVE OA_IOU2D` line must echo `0.4`
(the runner flags `effective_mismatch` otherwise → the exposure is not working; go back to Step 2).

## Step 4 — the matrix
Estimate the duration first: (number of sequences × cells × runs) × (sequence duration + ~20 s).
Tell the user the estimate and ask for approval, then run in the foreground of a dedicated terminal or under
`nohup`/`tmux` so that it survives a disconnect:
```
nohup python -m oa3.runner --config oa3_config.yaml > runner.out 2>&1 &
tail -f runner.out
```
The runner is resumable: re-running the same command skips finished runs. Failed runs are retried once;
runs with `low_coverage` are kept and flagged. Do not interpret partial results while it runs.

## Step 5 — evaluation and report
```
python -m oa3.evaluate --config oa3_config.yaml
python -m oa3.report   --config oa3_config.yaml --zip
```
Read `OA3_report.md`. Check: section 1 (no MISMATCH), section 2 (all runs evaluated), section 3
(control check). If the control check fails, look at the control runs' logs (`LOST`, `RELOC`, `jump`) and
report the cause candidates; do not silence the flag.

## Step 6 — hand-off (in Indonesian)
Give the user: the path of `oa3_handoff_*.zip`, the three figures, and a short summary per family
(mean Δ ATE on dynamic sequences, number of sequences with separated run-ranges, control status), taken
verbatim from the report. Remind that the numbers go to the manuscript's sensitivity/ablation paragraph and
to the "pending" rows of the responses to Reviewer A and Reviewer D.

## Useful commands
- Plan only: `python -m oa3.runner --config oa3_config.yaml --dry-run`
- Subset: `--only-seqs bonn_crowd,fr3_walking_half --only-cells default,P1_tight --runs 1`
- Re-evaluate with a different protocol after changing `evaluation:` in the config: `python -m oa3.evaluate ... --force`
- Mock self-test of the pipeline (no fork needed): `bash tests/run_mock_pipeline.sh --fast`
- Filter a detection file (OA-2 confidence sweep): `python -m oa3.filter_detections in.json out.json --min-score 0.6`
