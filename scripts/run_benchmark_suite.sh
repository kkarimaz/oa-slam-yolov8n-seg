#!/usr/bin/env bash
# Batch benchmark runner for OA-SLAM (yolov8n-seg) across multiple datasets.
# Runs each dataset N times headless, then evaluates ATE / RPE (trans+rot) with evo,
# and collects computation metrics (tracking time, FPS, CPU, RAM).
set -uo pipefail

REPO="/home/khansa/Documents/coding/oa-slam-yolov8n-seg"
BIN="$REPO/bin"
VOCAB="$REPO/Vocabulary/ORBvoc.txt"
ONNX="$REPO/yolov8n-seg.onnx"
IGNORE="null"
RELOC="points+objects"
RESULTS="$REPO/benchmark_results"
NRUNS=5

export LD_LIBRARY_PATH="/home/khansa/opt/opencv-4.8.0/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HOME/.local/bin:$PATH"
export OASLAM_HEADLESS=1

mkdir -p "$RESULTS"

# name|dataset_dir|camera_yaml
DATASETS=(
"TUM_fr3_sitting_xyz|/media/khansa/KINGSTON/Dataset/TUM_RGBD/fr3_sitting_xyz/rgbd_dataset_freiburg3_sitting_xyz|TUM3.yaml"
"TUM_fr3_walking_half|/media/khansa/KINGSTON/Dataset/TUM_RGBD/fr3_walking_halfsphere/rgbd_dataset_freiburg3_walking_halfsphere|TUM3.yaml"
"TUM_fr3_walking_xyz|/media/khansa/KINGSTON/Dataset/TUM_RGBD/fr3_walking_xyz/rgbd_dataset_freiburg3_walking_xyz|TUM3.yaml"
"TUM_fr2_desk_w_person|/media/khansa/KINGSTON/Dataset/TUM_RGBD/fr2_desk_w_person/rgbd_dataset_freiburg2_desk_with_person|TUM2.yaml"
"TUM_fr3_walking_static|/media/khansa/KINGSTON/Dataset/TUM_RGBD/fr3_walking_static/rgbd_dataset_freiburg3_walking_static|TUM3.yaml"
"TUM_fr3_walking_rpy|/media/khansa/KINGSTON/Dataset/TUM_RGBD/fr3_walking_rpy/rgbd_dataset_freiburg3_walking_rpy|TUM3.yaml"
"rgbd_bonn_crowd|/media/khansa/KINGSTON/Dataset/BONN/rgbd_bonn_crowd|TUM3.yaml"
"rgbd_bonn_person_track|/media/khansa/KINGSTON/Dataset/BONN/rgbd_bonn_person_tracking|TUM3.yaml"
"rgbd_bonn_crowd2|/media/khansa/KINGSTON/Dataset/BONN/rgbd_bonn_crowd2|TUM3.yaml"
"fr1_desk2|/media/khansa/KINGSTON/Dataset/TUM_RGBD/fr1_desk2/rgbd_dataset_freiburg1_desk2|TUM1.yaml"
"fr1_room|/media/khansa/KINGSTON/Dataset/TUM_RGBD/fr1_room/rgbd_dataset_freiburg1_room|TUM1.yaml"
"fr2_pioneer_slam|/media/khansa/KINGSTON/Dataset/TUM_RGBD/fr2_pioneer_slam/rgbd_dataset_freiburg2_pioneer_slam|TUM2.yaml"
)

SUMMARY_CSV="$RESULTS/summary_all_runs.csv"
if [ ! -f "$SUMMARY_CSV" ]; then
  echo "dataset,run,ate_rmse,ate_mean,ate_median,ate_std,ate_min,ate_max,rpe_trans_rmse,rpe_trans_mean,rpe_trans_median,rpe_trans_std,rpe_trans_min,rpe_trans_max,rpe_rot_rmse,rpe_rot_mean,rpe_rot_median,rpe_rot_std,rpe_rot_min,rpe_rot_max,median_tracking_time_s,mean_tracking_time_s,total_time_s,init_time_s,mean_fps,min_fps,max_fps,cpu_mean_pct,cpu_max_pct,ram_mean_mb,ram_max_mb,gpu_usage" > "$SUMMARY_CSV"
fi

get_evo_field() {
  # $1 = evo stdout, $2 = field
  echo "$1" | awk -v f="$2" '$1==f{print $2; found=1} END{if(!found) print "NA"}'
}

for entry in "${DATASETS[@]}"; do
  IFS='|' read -r name dpath cam <<< "$entry"
  gt="$dpath/groundtruth.txt"
  rgb="$dpath/rgb.txt"
  resultdir="$RESULTS/result_${name}"
  mkdir -p "$resultdir"

  for run in $(seq 1 "$NRUNS"); do
    rundir="$resultdir/run_${run}"
    if [ -f "$rundir/DONE" ]; then
      echo "[$(date '+%H:%M:%S')] SKIP (already done): $name run $run"
      continue
    fi
    rm -rf "$rundir"
    mkdir -p "$rundir"
    echo "[$(date '+%H:%M:%S')] === $name run $run/$NRUNS ==="

    logfile="$rundir/run_stdout.log"
    cpulog="$rundir/cpu_ram_samples.csv"
    : > "$cpulog"

    SECONDS=0
    (
      cd "$resultdir" || exit 1
      timeout -k 30 1200 "$BIN/oa-slam" "$VOCAB" "$REPO/Cameras/$cam" "$rgb" "$ONNX" "$IGNORE" "$RELOC" "run_${run}"
    ) > "$logfile" 2>&1 &
    slam_pid=$!

    # CPU/RAM sampler (samples the whole multi-threaded process)
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

    if [ "$slam_exit" -eq 124 ] || [ "$slam_exit" -eq 137 ]; then
      echo "  !! TIMEOUT: $name run $run killed after 1200s (deadlock/hang), see $logfile" | tee -a "$RESULTS/errors.log"
    elif [ "$slam_exit" -ne 0 ]; then
      echo "  !! oa-slam exited with code $slam_exit, see $logfile" | tee -a "$RESULTS/errors.log"
    fi

    est="$rundir/camera_poses_run_${run}_tum.txt"
    exec_csv="$rundir/total_execution_time.csv"

    # --- computation metrics from stdout log ---
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

    # init time = sum of tracking durations for frames processed before first successful map init
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

    # --- CPU / RAM ---
    if [ -s "$cpulog" ]; then
      read cpu_mean cpu_max ram_mean ram_max < <(awk '{cs+=$1; if($1>cmax)cmax=$1; rs+=$2; if($2>rmax)rmax=$2; n++} END{if(n>0) printf "%.2f %.2f %.2f %.2f", cs/n, cmax, rs/n/1024, rmax/1024; else print "NA NA NA NA"}' "$cpulog")
    else
      cpu_mean="NA"; cpu_max="NA"; ram_mean="NA"; ram_max="NA"
    fi
    gpu_usage="N/A (CPU-only build, no CUDA)"

    # --- evo: ATE, RPE translational, RPE rotational ---
    ate_out="NA"; rpe_t_out="NA"; rpe_r_out="NA"
    if [ -f "$est" ] && [ -f "$gt" ]; then
      ate_out=$(evo_ape tum "$gt" "$est" -as --save_results "$rundir/ate_results.zip" 2>>"$rundir/evo_errors.log")
      rpe_t_out=$(evo_rpe tum "$gt" "$est" -r trans_part -s --save_results "$rundir/rpe_trans_results.zip" 2>>"$rundir/evo_errors.log")
      rpe_r_out=$(evo_rpe tum "$gt" "$est" -r rot_part -s --save_results "$rundir/rpe_rot_results.zip" 2>>"$rundir/evo_errors.log")
    else
      echo "  !! missing estimate ($est) or groundtruth ($gt), skipping evo" | tee -a "$RESULTS/errors.log"
    fi

    ate_rmse=$(get_evo_field "$ate_out" rmse); ate_mean=$(get_evo_field "$ate_out" mean)
    ate_median=$(get_evo_field "$ate_out" median); ate_std=$(get_evo_field "$ate_out" std)
    ate_min=$(get_evo_field "$ate_out" min); ate_max=$(get_evo_field "$ate_out" max)

    rt_rmse=$(get_evo_field "$rpe_t_out" rmse); rt_mean=$(get_evo_field "$rpe_t_out" mean)
    rt_median=$(get_evo_field "$rpe_t_out" median); rt_std=$(get_evo_field "$rpe_t_out" std)
    rt_min=$(get_evo_field "$rpe_t_out" min); rt_max=$(get_evo_field "$rpe_t_out" max)

    rr_rmse=$(get_evo_field "$rpe_r_out" rmse); rr_mean=$(get_evo_field "$rpe_r_out" mean)
    rr_median=$(get_evo_field "$rpe_r_out" median); rr_std=$(get_evo_field "$rpe_r_out" std)
    rr_min=$(get_evo_field "$rpe_r_out" min); rr_max=$(get_evo_field "$rpe_r_out" max)

    echo "$name,$run,$ate_rmse,$ate_mean,$ate_median,$ate_std,$ate_min,$ate_max,$rt_rmse,$rt_mean,$rt_median,$rt_std,$rt_min,$rt_max,$rr_rmse,$rr_mean,$rr_median,$rr_std,$rr_min,$rr_max,$median_tt,$mean_tt,$total_time,$init_time,$mean_fps,$min_fps,$max_fps,$cpu_mean,$cpu_max,$ram_mean,$ram_max,\"$gpu_usage\"" >> "$SUMMARY_CSV"

    touch "$rundir/DONE"
    echo "  done in ${total_time}s (ATE rmse=$ate_rmse, mean_fps=$mean_fps)"
  done
done

echo "[$(date '+%H:%M:%S')] ALL RUNS COMPLETE. Summary: $SUMMARY_CSV"
