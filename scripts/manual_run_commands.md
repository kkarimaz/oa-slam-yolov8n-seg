# Manual CLI commands per dataset

Catatan penting:
- `output_name` (argumen ke-7) **harus nama pendek tanpa path** (bukan full path) — kalau diisi
  path, ada bug di `Examples/oa-slam.cc` yang bikin nama file output jadi rusak/gagal ke-save
  secara diam-diam. Makanya pola di bawah selalu `cd` dulu ke folder tujuan, baru run dengan
  `output_name` = nama pendek (`run`).
- `OASLAM_HEADLESS=1` (opsional) mematikan window Map/AR Viewer — dipakai di batch otomatis
  karena lebih representatif buat benchmarking murni (compute) dan gak butuh display. Hapus env
  var ini kalau mau lihat viewer-nya jalan interaktif.
- Semua dataset di bawah pakai relocalization mode `points+objects` dan model
  `yolov8n-seg.onnx`, sama seperti run awal kita.

Ganti `run` di baris `cd .../run_N` dan argumen terakhir jadi `run_1`, `run_2`, dst kalau mau
run berkali-kali manual (biar gak numpuk di folder yang sama).

```bash
REPO=/home/khansa/Documents/coding/oa-slam-yolov8n-seg
VOCAB="$REPO/Vocabulary/ORBvoc.txt"
ONNX="$REPO/yolov8n-seg.onnx"
```

## TUM_fr3_sitting_xyz (1261 frames, TUM3.yaml)
```bash
mkdir -p "$REPO/benchmark_results/result_TUM_fr3_sitting_xyz/run_1" && cd "$_"
OASLAM_HEADLESS=1 "$REPO/bin/oa-slam" "$VOCAB" "$REPO/Cameras/TUM3.yaml" \
  /media/khansa/KINGSTON/Dataset/TUM_RGBD/fr3_sitting_xyz/rgbd_dataset_freiburg3_sitting_xyz/rgb.txt \
  "$ONNX" null points+objects run
```

## TUM_fr3_walking_half (1067 frames, TUM3.yaml)
```bash
mkdir -p "$REPO/benchmark_results/result_TUM_fr3_walking_half/run_1" && cd "$_"
OASLAM_HEADLESS=1 "$REPO/bin/oa-slam" "$VOCAB" "$REPO/Cameras/TUM3.yaml" \
  /media/khansa/KINGSTON/Dataset/TUM_RGBD/fr3_walking_halfsphere/rgbd_dataset_freiburg3_walking_halfsphere/rgb.txt \
  "$ONNX" null points+objects run
```

## TUM_fr3_walking_xyz (859 frames, TUM3.yaml)
```bash
mkdir -p "$REPO/benchmark_results/result_TUM_fr3_walking_xyz/run_1" && cd "$_"
OASLAM_HEADLESS=1 "$REPO/bin/oa-slam" "$VOCAB" "$REPO/Cameras/TUM3.yaml" \
  /media/khansa/KINGSTON/Dataset/TUM_RGBD/fr3_walking_xyz/rgbd_dataset_freiburg3_walking_xyz/rgb.txt \
  "$ONNX" null points+objects run
```

## TUM_fr2_desk_w_person (4067 frames, TUM2.yaml)
```bash
mkdir -p "$REPO/benchmark_results/result_TUM_fr2_desk_w_person/run_1" && cd "$_"
OASLAM_HEADLESS=1 "$REPO/bin/oa-slam" "$VOCAB" "$REPO/Cameras/TUM2.yaml" \
  /media/khansa/KINGSTON/Dataset/TUM_RGBD/fr2_desk_w_person/rgbd_dataset_freiburg2_desk_with_person/rgb.txt \
  "$ONNX" null points+objects run
```

## TUM_fr3_walking_static (743 frames, TUM3.yaml)
```bash
mkdir -p "$REPO/benchmark_results/result_TUM_fr3_walking_static/run_1" && cd "$_"
OASLAM_HEADLESS=1 "$REPO/bin/oa-slam" "$VOCAB" "$REPO/Cameras/TUM3.yaml" \
  /media/khansa/KINGSTON/Dataset/TUM_RGBD/fr3_walking_static/rgbd_dataset_freiburg3_walking_static/rgb.txt \
  "$ONNX" null points+objects run
```

## TUM_fr3_walking_rpy (910 frames, TUM3.yaml)
```bash
mkdir -p "$REPO/benchmark_results/result_TUM_fr3_walking_rpy/run_1" && cd "$_"
OASLAM_HEADLESS=1 "$REPO/bin/oa-slam" "$VOCAB" "$REPO/Cameras/TUM3.yaml" \
  /media/khansa/KINGSTON/Dataset/TUM_RGBD/fr3_walking_rpy/rgbd_dataset_freiburg3_walking_rpy/rgb.txt \
  "$ONNX" null points+objects run
```

## rgbd_bonn_crowd (928 frames, TUM3.yaml — Bonn pakai sensor sama dgn TUM fr3)
```bash
mkdir -p "$REPO/benchmark_results/result_rgbd_bonn_crowd/run_1" && cd "$_"
OASLAM_HEADLESS=1 "$REPO/bin/oa-slam" "$VOCAB" "$REPO/Cameras/TUM3.yaml" \
  /media/khansa/KINGSTON/Dataset/BONN/rgbd_bonn_crowd/rgb.txt \
  "$ONNX" null points+objects run
```

## rgbd_bonn_person_track (580 frames, TUM3.yaml)
```bash
mkdir -p "$REPO/benchmark_results/result_rgbd_bonn_person_track/run_1" && cd "$_"
OASLAM_HEADLESS=1 "$REPO/bin/oa-slam" "$VOCAB" "$REPO/Cameras/TUM3.yaml" \
  /media/khansa/KINGSTON/Dataset/BONN/rgbd_bonn_person_tracking/rgb.txt \
  "$ONNX" null points+objects run
```

## rgbd_bonn_crowd2 (895 frames, TUM3.yaml)
```bash
mkdir -p "$REPO/benchmark_results/result_rgbd_bonn_crowd2/run_1" && cd "$_"
OASLAM_HEADLESS=1 "$REPO/bin/oa-slam" "$VOCAB" "$REPO/Cameras/TUM3.yaml" \
  /media/khansa/KINGSTON/Dataset/BONN/rgbd_bonn_crowd2/rgb.txt \
  "$ONNX" null points+objects run
```

## fr1_desk2 (640 frames, TUM1.yaml)
```bash
mkdir -p "$REPO/benchmark_results/result_fr1_desk2/run_1" && cd "$_"
OASLAM_HEADLESS=1 "$REPO/bin/oa-slam" "$VOCAB" "$REPO/Cameras/TUM1.yaml" \
  /media/khansa/KINGSTON/Dataset/TUM_RGBD/fr1_desk2/rgbd_dataset_freiburg1_desk2/rgb.txt \
  "$ONNX" null points+objects run
```

## fr1_room (1362 frames, TUM1.yaml)
```bash
mkdir -p "$REPO/benchmark_results/result_fr1_room/run_1" && cd "$_"
OASLAM_HEADLESS=1 "$REPO/bin/oa-slam" "$VOCAB" "$REPO/Cameras/TUM1.yaml" \
  /media/khansa/KINGSTON/Dataset/TUM_RGBD/fr1_room/rgbd_dataset_freiburg1_room/rgb.txt \
  "$ONNX" null points+objects run
```

## fr2_pioneer_slam (2921 frames, TUM2.yaml)
```bash
mkdir -p "$REPO/benchmark_results/result_fr2_pioneer_slam/run_1" && cd "$_"
OASLAM_HEADLESS=1 "$REPO/bin/oa-slam" "$VOCAB" "$REPO/Cameras/TUM2.yaml" \
  /media/khansa/KINGSTON/Dataset/TUM_RGBD/fr2_pioneer_slam/rgbd_dataset_freiburg2_pioneer_slam/rgb.txt \
  "$ONNX" null points+objects run
```

## Evaluasi manual (ATE, RPE translational, RPE rotational) setelah run selesai
Ganti `<dataset_gt_folder>` dan `<run_folder>` sesuai dataset yang barusan di-run.
```bash
export PATH="$HOME/.local/bin:$PATH"
evo_ape tum <dataset_gt_folder>/groundtruth.txt <run_folder>/camera_poses_run_tum.txt -as --save_results ate.zip
evo_rpe tum <dataset_gt_folder>/groundtruth.txt <run_folder>/camera_poses_run_tum.txt -r trans_part -s --save_results rpe_trans.zip
evo_rpe tum <dataset_gt_folder>/groundtruth.txt <run_folder>/camera_poses_run_tum.txt -r rot_part -s --save_results rpe_rot.zip
```
