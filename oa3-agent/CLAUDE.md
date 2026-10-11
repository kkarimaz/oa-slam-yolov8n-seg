# oa3-agent — OA-3 ablation of OA-SLAM-YOLOv8n (IJRA revision, Reviewers A & D)

Purpose: one-factor-at-a-time sensitivity analysis of the OA-SLAM object-association parameters
(P1 association IoU gates, P2 minimum observations, P3 person landmarks), N repeated runs per cell,
evaluated with evo exactly like the manuscript, reported as tables + figures for the paper.

Layout
- `oa3_config.yaml` — the campaign (paths, cells, evaluation protocol). Edit this first.
- `oa3/preflight.py` → `tools/patch_params.py` → `oa3/runner.py` → `oa3/evaluate.py` → `oa3/report.py`
- `tools/mock_oa_slam.py`, `tests/run_mock_pipeline.sh` — mock executable and end-to-end self-test.
- `.claude/skills/oa3-ablation/SKILL.md` — the operating procedure. Follow it; it has the approval gates.

Rules for any session in this folder
- Speak Indonesian to the user; keep English in code, logs and reports.
- Never change detector/weights/confidence 0.5/ORB/camera settings; no TensorRT; one run at a time.
- Ask before patching/rebuilding the fork, deleting results, or launching the full matrix.
- Numbers only from the scripts' outputs. If something cannot be verified, say so.
- Python ≥ 3.8; run modules from this folder: `python -m oa3.<module> --config oa3_config.yaml`.
