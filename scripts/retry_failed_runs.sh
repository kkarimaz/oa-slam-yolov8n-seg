#!/usr/bin/env bash
# Retries specific (dataset, run) slots that previously timed out, after the
# KeyFrame::mMutexConnections recursive_mutex fix. Keeps retrying each slot
# (up to MAX_ATTEMPTS) until it succeeds, then patches summary_all_runs.csv.
set -uo pipefail

REPO="/home/khansa/Documents/coding/oa-slam-yolov8n-seg"
BIN="$REPO/bin"
VOCAB="$REPO/Vocabulary/ORBvoc.txt"
ONNX="$REPO/yolov8n-seg.onnx"
IGNORE="null"
RELOC="points+objects"
RESULTS="$REPO/benchmark_results"
SUMMARY_CSV="$RESULTS/summary_all_runs.csv"
MAX_ATTEMPTS=5

export LD_LIBRARY_PATH="/home/khansa/opt/opencv-4.8.0/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/bin:$PATH"
export OASLAM_HEADLESS=1

# name|dataset_dir|camera_yaml|run_number
TARGETS=(
"TUM_fr3_sitting_xyz|/media/khansa/KINGSTON/Dataset/TUM_RGBD/fr3_sitting_xyz/rgbd_dataset_freiburg3_sitting_xyz|TUM3.yaml|3"
"TUM_fr3_sitting_xyz|/media/khansa/KINGSTON/Dataset/TUM_RGBD/fr3_sitting_xyz/rgbd_dataset_freiburg3_sitting_xyz|TUM3.yaml|5"
"TUM_fr2_desk_w_person|/media/khansa/KINGSTON/Dataset/TUM_RGBD/fr2_desk_w_person/rgbd_dataset_freiburg2_desk_with_person|TUM2.yaml|4"
"rgbd_bonn_crowd|/media/khansa/KINGSTON/Dataset/BONN/rgbd_bonn_crowd|TUM3.yaml|1"
"rgbd_bonn_crowd|/media/khansa/KINGSTON/Dataset/BONN/rgbd_bonn_crowd|TUM3.yaml|2"
"rgbd_bonn_crowd|/media/khansa/KINGSTON/Dataset/BONN/rgbd_bonn_crowd|TUM3.yaml|4"
"rgbd_bonn_crowd|/media/khansa/KINGSTON/Dataset/BONN/rgbd_bonn_crowd|TUM3.yaml|5"
)

get_evo_field() {
  echo "$1" | awk -v f="$2" '$1==f{print $2; found=1} END{if(!found) print "NA"}'
}

for entry in "${TARGETS[@]}"; do
  IFS='|' read -r name dpath cam run <<< "$entry"
  gt="$dpath/groundtruth.txt"
  rgb="$dpath/rgb.txt"
  resultdir="$RESULTS/result_${name}"
  rundir="$resultdir/run_${run}"

  success=0
  for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    echo "[$(date '+%H:%M:%S')] === RETRY $name run $run (attempt $attempt/$MAX_ATTEMPTS) ==="
    rm -rf "$rundir"
    mkdir -p "$rundir"
    logfile="$rundir/run_stdout.log"
    cpulog="$rundir/cpu_ram_samples.csv"
    : > "$cpulog"

    SECONDS=0
    (
      cd "$resultdir" || exit 1
      timeout -k 30 1200 "$BIN/oa-slam" "$VOCAB" "$REPO/Cameras/$cam" "$rgb" "$ONNX" "$IGNORE" "$RELOC" "run_${run}"
    ) > "$logfile" 2>&1 &
    slam_pid=$!

    (
      while kill -0 "$slam_pid" 2>/dev/null; do
        ps -o %cpu=,rss= -p "$slam_pid" 2>/dev/null >> "$cpulog"
        sleep 2
      done
    ) &
    sampler_pid=$!

    wait "$slam_pid"
    slam_exit=$?
    total_time=$SECONDS
    kill "$sampler_pid" 2>/dev/null
    wait "$sampler_pid" 2>/dev/null

    est="$rundir/camera_poses_run_${run}_tum.txt"
    if [ "$slam_exit" -eq 124 ] || [ "$slam_exit" -eq 137 ]; then
      echo "  !! attempt $attempt TIMEOUT again" | tee -a "$RESULTS/errors.log"
      continue
    fi
    if [ "$slam_exit" -ne 0 ] || [ ! -f "$est" ]; then
      echo "  !! attempt $attempt failed (exit=$slam_exit, no estimate file)" | tee -a "$RESULTS/errors.log"
      continue
    fi

    success=1
    exec_csv="$rundir/total_execution_time.csv"

    median_tt=$(grep "median tracking time:" "$logfile" | awk '{print $NF}')
    mean_tt=$(grep "mean tracking time:" "$logfile" | awk '{print $NF}')
    [ -z "$median_tt" ] && median_tt="NA"
    [ -z "$mean_tt" ] && mean_tt="NA"

    fps_values=$(grep "^FPS = " "$logfile" | awk '{print $3}' | grep -Ei '^[0-9.]+$')
    if [ -n "$fps_values" ]; then
      min_fps=$(echo "$fps_values" | sort -g | head -1)
      max_fps=$(echo "$fps_values" | sort -g | tail -1)
      mean_fps=$(echo "$fps_values" | awk '{s+=$1;n++} END{if(n>0) printf "%.4f", s/n; else print "NA"}')
    else
      min_fps="NA"; max_fps="NA"; mean_fps="NA"
    fi

    if [ -f "$exec_csv" ]; then
      n_before_init=$(awk '/New Map created/{exit} /^FPS = /{c++} END{print c+0}' "$logfile")
      if [ "$n_before_init" -gt 0 ] 2>/dev/null; then
        init_time=$(tail -n +2 "$exec_csv" | head -n "$n_before_init" | awk -F, '{s+=$2} END{printf "%.4f", s}')
      else
        init_time="NA"
      fi
    else
      init_time="NA"
    fi

    if [ -s "$cpulog" ]; then
      read cpu_mean cpu_max ram_mean ram_max < <(awk '{cs+=$1; if($1>cmax)cmax=$1; rs+=$2; if($2>rmax)rmax=$2; n++} END{if(n>0) printf "%.2f %.2f %.2f %.2f", cs/n, cmax, rs/n/1024, rmax/1024; else print "NA NA NA NA"}' "$cpulog")
    else
      cpu_mean="NA"; cpu_max="NA"; ram_mean="NA"; ram_max="NA"
    fi
    gpu_usage="N/A (CPU-only build, no CUDA)"

    ate_out=$(evo_ape tum "$gt" "$est" -as --save_results "$rundir/ate_results.zip" 2>>"$rundir/evo_errors.log")
    rpe_t_out=$(evo_rpe tum "$gt" "$est" -r trans_part -s --save_results "$rundir/rpe_trans_results.zip" 2>>"$rundir/evo_errors.log")
    rpe_r_out=$(evo_rpe tum "$gt" "$est" -r rot_part -s --save_results "$rundir/rpe_rot_results.zip" 2>>"$rundir/evo_errors.log")

    ate_rmse=$(get_evo_field "$ate_out" rmse); ate_mean=$(get_evo_field "$ate_out" mean)
    ate_median=$(get_evo_field "$ate_out" median); ate_std=$(get_evo_field "$ate_out" std)
    ate_min=$(get_evo_field "$ate_out" min); ate_max=$(get_evo_field "$ate_out" max)

    rt_rmse=$(get_evo_field "$rpe_t_out" rmse); rt_mean=$(get_evo_field "$rpe_t_out" mean)
    rt_median=$(get_evo_field "$rpe_t_out" median); rt_std=$(get_evo_field "$rpe_t_out" std)
    rt_min=$(get_evo_field "$rpe_t_out" min); rt_max=$(get_evo_field "$rpe_t_out" max)

    rr_rmse=$(get_evo_field "$rpe_r_out" rmse); rr_mean=$(get_evo_field "$rpe_r_out" mean)
    rr_median=$(get_evo_field "$rpe_r_out" median); rr_std=$(get_evo_field "$rpe_r_out" std)
    rr_min=$(get_evo_field "$rpe_r_out" min); rr_max=$(get_evo_field "$rpe_r_out" max)

    # remove old (NA) row for this dataset+run, then append the fresh one
    awk -F, -v d="$name" -v r="$run" 'NR==1{print; next} !($1==d && $2==r){print}' "$SUMMARY_CSV" > "$SUMMARY_CSV.tmp" && mv "$SUMMARY_CSV.tmp" "$SUMMARY_CSV"
    echo "$name,$run,$ate_rmse,$ate_mean,$ate_median,$ate_std,$ate_min,$ate_max,$rt_rmse,$rt_mean,$rt_median,$rt_std,$rt_min,$rt_max,$rr_rmse,$rr_mean,$rr_median,$rr_std,$rr_min,$rr_max,$median_tt,$mean_tt,$total_time,$init_time,$mean_fps,$min_fps,$max_fps,$cpu_mean,$cpu_max,$ram_mean,$ram_max,\"$gpu_usage\"" >> "$SUMMARY_CSV"

    touch "$rundir/DONE"
    echo "  SUCCESS on attempt $attempt (${total_time}s, ATE rmse=$ate_rmse, mean_fps=$mean_fps)"
    break
  done

  if [ "$success" -eq 0 ]; then
    echo "  !! GAVE UP on $name run $run after $MAX_ATTEMPTS attempts, still deadlocking" | tee -a "$RESULTS/errors.log"
  fi
done

echo "[$(date '+%H:%M:%S')] RETRY PASS COMPLETE."
