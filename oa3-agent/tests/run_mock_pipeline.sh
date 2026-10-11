#!/usr/bin/env bash
# End-to-end self-test of the OA-3 pipeline with the mock OA-SLAM (no build, no dataset needed). ~2 min.
#   bash tests/run_mock_pipeline.sh            # 3 sequences x 6 cells x 3 runs
#   bash tests/run_mock_pipeline.sh --fast     # 1 run per cell
set -euo pipefail
cd "$(dirname "$0")/.."
RUNS=3; [[ "${1:-}" == "--fast" ]] && RUNS=1
rm -rf results_mock mock_data mock_root oa3_config_mock.yaml
python3 tools/make_mock_dataset.py --frames 300
python3 -m oa3.preflight --config oa3_config_mock.yaml --mock
python3 -m oa3.runner    --config oa3_config_mock.yaml --mock --runs $RUNS
# resume: a second invocation must skip every finished run
python3 -m oa3.runner    --config oa3_config_mock.yaml --mock --runs $RUNS > results_mock/_resume.out
grep -q "skipped (done)=" results_mock/_resume.out && echo "[test] resume OK"
# retry: simulate one crash of a run and check that the retry path recovers it
rm -rf results_mock/mock_control/P2_high/run01
rm -f mock_root/.mock_failed_once_*
OA3_MOCK_FAIL_ONCE=mock_control__P2_high__run01 python3 -m oa3.runner --config oa3_config_mock.yaml --mock --runs $RUNS --only-seqs mock_control --only-cells P2_high > results_mock/_retry.out || true
grep -q "RETRY" results_mock/_retry.out && echo "[test] retry OK"
grep -q '"status": "ok"' results_mock/mock_control/P2_high/run01/meta.json || grep -q '"status": "low_coverage"' results_mock/mock_control/P2_high/run01/meta.json || { echo "[test] retry did not recover"; exit 1; }
python3 -m oa3.evaluate  --config oa3_config_mock.yaml --evo auto
python3 -m oa3.report    --config oa3_config_mock.yaml --zip
for f in oa3_results.csv oa3_cell_summary.csv oa3_summary.json OA3_report.md fig_oa3_ate.png fig_oa3_rpe.png fig_oa3_map.png platform.json config_used.yaml; do
  [[ -s "results_mock/$f" ]] || { echo "[test] MISSING results_mock/$f"; exit 1; }
done
ls results_mock/oa3_handoff_*.zip >/dev/null
n=$(python3 - <<'EOF'
import csv; print(sum(1 for _ in csv.DictReader(open("results_mock/oa3_results.csv"))))
EOF
)
echo "[test] evaluated runs: $n"
echo "[test] mock pipeline OK -> results_mock/OA3_report.md"
