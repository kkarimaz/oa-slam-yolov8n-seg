#!/usr/bin/env python3
"""Mock of the (patched) OA-SLAM executable, used to test the OA-3 pipeline end-to-end without a build.

Accepts the upstream command line (7 positional args) or the 8-arg variant with categories_to_ignore_file:
  mock vocabulary_file camera_file path_to_image_sequence detections_file [ignore_file] reloc_mode output_name show_viewer
Reads the parameters from the environment exactly like include/oa3_params.h, prints the same log lines
(EFFECTIVE, Frame/Nb Map Objects, FRAME, ASSOC, LANDMARK_NEW, LOST, RELOC, mean/median tracking time) and writes
into <cwd>/<output_name>/ the files camera_poses_<name>_tum.txt, keyframes_poses_<name>_tum.txt,
map_objects_<name>.txt (dual quadrics, column-major, Q(3,3) = -1) and map_<name>.yaml.
The synthetic trajectory is the ground truth of the sequence folder plus drift/jumps that depend on the parameters,
so that the report has something to show. It has NO scientific meaning.
"""
import hashlib, json, math, os, sys, time
from pathlib import Path
import numpy as np


def env_f(k, d):
    v = os.environ.get(k)
    return float(v) if v not in (None, "") else d


def env_i(k, d):
    v = os.environ.get(k)
    return int(float(v)) if v not in (None, "") else d


def read_list(path):
    ts, names = [], []
    with open(path) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            p = s.split()
            ts.append(float(p[0])); names.append(p[-1])
    return ts, names


def read_gt(path):
    rows = []
    with open(path) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            rows.append([float(x) for x in s.split()[:8]])
    return np.array(rows)


def quat_mul(a, b):  # [x,y,z,w]
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return np.array([aw*bx + ax*bw + ay*bz - az*by, aw*by - ax*bz + ay*bw + az*bx, aw*bz + ax*by - ay*bx + az*bw, aw*bw - ax*bx - ay*by - az*bz])


def dual_quadric(center, axes, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
    Q = np.diag([axes[0] ** 2, axes[1] ** 2, axes[2] ** 2, -1.0])
    T = np.eye(4); T[:3, :3] = R; T[:3, 3] = center
    Q = T @ Q @ T.T
    Q = 0.5 * (Q + Q.T)
    return Q / (-Q[3, 3])


def main():
    argv = sys.argv[1:]
    if len(argv) not in (7, 8):
        print("Usage: mock vocabulary_file camera_file path_to_image_sequence detections_file [ignore_file] reloc_mode output_name show_viewer")
        return 1
    if len(argv) == 8:
        vocab, cam, seq, det_file, ignore_file, reloc_mode, out_name, show = argv
    else:
        vocab, cam, seq, det_file, reloc_mode, out_name, show = argv; ignore_file = ""
    if reloc_mode not in ("points", "objects", "points+objects"):
        print("Error: Invalid parameter for relocalization mode."); return 1
    if os.environ.get("OA3_MOCK_FAIL") and os.environ["OA3_MOCK_FAIL"] in out_name:
        print("mock: simulated crash"); return 3
    if os.environ.get("OA3_MOCK_FAIL_ONCE") and os.environ["OA3_MOCK_FAIL_ONCE"] in out_name:
        marker = Path(".mock_failed_once_" + out_name)      # fail the first attempt only (tests the retry path)
        if not marker.exists():
            marker.write_text("1"); print("mock: simulated crash (once)"); return 3
        marker.unlink()

    P = dict(det_score=env_f("OA_DET_SCORE", 0.5), iou2d=env_f("OA_IOU2D", 0.2), iou3d=env_f("OA_IOU3D", 0.3),
             time_diff=env_i("OA_TIME_DIFF", 30), nb_match=env_i("OA_NB_MATCH", 10), min_obs=env_i("OA_MIN_OBS", 10), map_obs=env_i("OA_MAP_OBS", 40))
    print("C++ version: 201703 (mock)")
    print("EFFECTIVE OA_DET_SCORE=%g\nEFFECTIVE OA_IOU2D=%g\nEFFECTIVE OA_IOU3D=%g\nEFFECTIVE OA_TIME_DIFF=%d\nEFFECTIVE OA_NB_MATCH=%d\nEFFECTIVE OA_MIN_OBS=%d\nEFFECTIVE OA_MAP_OBS=%d" % (
        P["det_score"], P["iou2d"], P["iou3d"], P["time_diff"], P["nb_match"], P["min_obs"], P["map_obs"]))

    # image list: folder with rgb.txt or a .txt file
    seq_path = Path(seq)
    list_file = seq_path if seq_path.suffix == ".txt" else seq_path / "rgb.txt"
    ts, names = read_list(list_file)
    gt_file = list_file.parent / "groundtruth.txt"
    gt = read_gt(gt_file)
    n = len(ts)
    print("\n-------\nStart processing sequence ...\nImages in the sequence: %d\n" % n)

    # detections: persons present?
    with open(det_file) as f:
        det = json.load(f)
    ignored = set()
    if ignore_file and Path(ignore_file).exists():
        ignored = set(int(x) for x in Path(ignore_file).read_text().split() if x.strip().lstrip("-").isdigit())
    n_person = sum(1 for fr in det for d in fr.get("detections", []) if int(d.get("category_id", -1)) == 0 and 0 not in ignored and float(d.get("detection_score", 0)) > P["det_score"])
    n_det = sum(1 for fr in det for d in fr.get("detections", []) if int(d.get("category_id", -1)) not in ignored and float(d.get("detection_score", 0)) > P["det_score"])

    seed = int(hashlib.md5(out_name.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)

    # parameter-dependent behaviour (synthetic!)
    loose = max(0.0, 0.2 - P["iou2d"]) / 0.2          # 0 at default, 0.5 at 0.1
    tight = max(0.0, P["iou2d"] - 0.2) / 0.2          # 0 at default, 1 at 0.4
    obs_fac = 10.0 / max(1, P["min_obs"])              # 2 at 5, 0.5 at 20
    person_rate = n_person / max(1, n)                 # dynamic content that is used as landmarks
    drift_sigma = 0.004 * (1 + 0.6 * loose + 0.3 * tight) * (1 + 0.5 * person_rate)
    jump_p = (0.0015 + 0.006 * person_rate) * (1 + loose)
    n_landmarks = int(rng.poisson(6 * (1 + 0.8 * loose) * (0.6 + 0.4 * obs_fac) + 2 * person_rate * 10))
    n_dup = int(rng.binomial(n_landmarks, min(0.6, 0.08 + 0.35 * loose + 0.15 * max(0, obs_fac - 1))))

    # trajectory: GT (interpolated to frame timestamps) + random-walk drift + occasional jumps + lost episodes
    gts = gt[:, 0]
    idx = np.clip(np.searchsorted(gts, np.array(ts)), 0, len(gt) - 1)
    pos = gt[idx, 1:4].copy(); quat = gt[idx, 4:8].copy()
    drift = np.cumsum(rng.normal(0, drift_sigma, size=(n, 3)), axis=0)
    drift -= drift.mean(0)
    tracked = np.ones(n, bool); tracked[:12] = False        # initialisation
    times_ms = []
    track_ids = 0; in_map = 0; tracks = 0
    lost_until = -1
    for i in range(n):
        t0 = time.perf_counter()
        if i >= 12 and rng.random() < jump_p:                 # relocalisation jump: offset + short lost episode
            lost_len = int(rng.integers(3, 25))
            lost_until = i + lost_len
            drift[i:] += rng.normal(0, 0.25, 3)
        if 12 <= i <= lost_until:
            tracked[i] = False
            print("LOST %d" % i)
            ok = 1 if i == lost_until else 0
            print("RELOC %d %d %.3f" % (i, ok, float(rng.uniform(15, 60))))
        print("Frame %d ===========" % i)
        if i >= 12 and tracked[i]:
            if rng.random() < 0.3 * (1 + loose):
                track_ids += 1; tracks += 1
                print("ASSOC %d new %d" % (i, track_ids))
            if tracks and rng.random() < 0.8:
                print("ASSOC %d matched %d" % (i, int(rng.integers(1, track_ids + 1))))
            if in_map < n_landmarks and i > P["map_obs"] and rng.random() < n_landmarks / max(1.0, n - P["map_obs"]) * 1.2:
                in_map += 1
                print("LANDMARK_NEW %d %d %d" % (i, in_map, int(rng.choice([0, 56, 62, 63, 66, 73]))))
        print("Nb Object Tracks: %d" % tracks)
        print("Nb Map Objects  : %d" % in_map)
        ms = float(rng.normal(28 + 6 * obs_fac, 4)); times_ms.append(max(5.0, ms))
        print("FRAME %d %.3f" % (i, times_ms[-1]))
    est = pos + drift

    out_dir = Path(out_name); out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / ("camera_poses_%s_tum.txt" % out_name), "w") as f:
        for i in range(n):
            if tracked[i]:
                f.write("%.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f\n" % (ts[i], est[i, 0], est[i, 1], est[i, 2], quat[i, 0], quat[i, 1], quat[i, 2], quat[i, 3]))
            else:
                f.write("%.6f 0 0 0 0 0 0 1\n" % ts[i])
    with open(out_dir / ("keyframes_poses_%s_tum.txt" % out_name), "w") as f:
        for i in range(12, n, 10):
            if tracked[i]:
                f.write("%.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f\n" % (ts[i], est[i, 0], est[i, 1], est[i, 2], quat[i, 0], quat[i, 1], quat[i, 2], quat[i, 3]))
    with open(out_dir / ("map_objects_%s.txt" % out_name), "w") as f:
        cats = [int(c) for c in rng.choice([56, 62, 63, 66, 73, 0], size=max(0, n_landmarks - n_dup))]
        centers = [rng.uniform(-2, 2, 3) for _ in cats]
        objs = list(zip(cats, centers))
        for k in range(n_dup):           # duplicate = same class, centre very close to an existing landmark
            if not objs:
                break
            c0, cen0 = objs[int(rng.integers(0, len(objs)))]
            objs.append((c0, cen0 + rng.normal(0, 0.08, 3)))
        for tid, (c, cen) in enumerate(objs):
            Q = dual_quadric(cen, rng.uniform(0.15, 0.45, 3), float(rng.uniform(0, math.pi)))
            f.write("%d %d %s\n" % (tid, c, " ".join("%.8f" % v for v in Q.flatten(order="F"))))
    (out_dir / ("map_%s.yaml" % out_name)).write_text("mock: true\n")
    (out_dir / ("map_objects_%s.obj" % out_name)).write_text("# mock\n")
    tm = sorted(times_ms)
    print("-------\n\nmedian tracking time: %.6f\nmean tracking time: %.6f\n" % (tm[len(tm) // 2] / 1000.0, sum(tm) / len(tm) / 1000.0))
    print("Save map objects in %s" % (out_dir / ("map_objects_%s.txt" % out_name)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
