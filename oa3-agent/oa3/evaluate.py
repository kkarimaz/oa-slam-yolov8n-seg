"""Evaluate every completed run: ATE / RPE (evo, with a built-in fallback), log counters, landmarks and duplicates.

Usage:  python -m oa3.evaluate --config oa3_config.yaml [--evo auto|evo|builtin] [--force]
Writes  <results_root>/oa3_results.csv  (one row per run) and per-run eval.json.

Protocol (keep identical to the manuscript):
  * trajectory  = project.trajectory_for_eval (camera_poses_<out_name>_tum.txt by default)
  * untracked frames (identity pose) are dropped when evaluation.drop_identity_poses is true
  * ATE = evo_ape tum GT EST -a (SE(3) Umeyama)   [-as when align_scale is true]
  * RPE = evo_rpe tum GT EST -a --delta 1 --delta_unit f
"""
from __future__ import annotations
import argparse, csv, json, re, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path
import numpy as np
from .common import load_config, resolve, results_root, cells, fmt, is_identity_pose, log, read_json, write_json


# ----------------------------------------------------------------------------- trajectory utilities
def read_tum(path) -> np.ndarray:
    rows = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            v = s.replace(",", " ").split()
            if len(v) < 8:
                continue
            rows.append([float(x) for x in v[:8]])
    return np.array(rows) if rows else np.zeros((0, 8))


def write_tracked_copy(src: Path, dst: Path) -> dict:
    """Copy a TUM trajectory without identity (untracked) rows."""
    kept = dropped = 0
    with open(src, "r", encoding="utf-8", errors="ignore") as fi, open(dst, "w", encoding="utf-8") as fo:
        for line in fi:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            v = s.replace(",", " ").split()
            if len(v) < 8:
                continue
            if is_identity_pose(v):
                dropped += 1
                continue
            fo.write(" ".join(v[:8]) + "\n"); kept += 1
    return {"kept": kept, "dropped": dropped}


def quat_to_R(q):  # q = [qx, qy, qz, qw]
    x, y, z, w = q
    n = np.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def associate(gt: np.ndarray, est: np.ndarray, max_diff: float):
    """Nearest-timestamp association (est -> gt)."""
    if len(gt) == 0 or len(est) == 0:
        return np.zeros((0,), int), np.zeros((0,), int)
    gi, ei = [], []
    gts = gt[:, 0]
    for i, t in enumerate(est[:, 0]):
        k = int(np.searchsorted(gts, t))
        cands = [c for c in (k - 1, k) if 0 <= c < len(gts)]
        best = min(cands, key=lambda c: abs(gts[c] - t))
        if abs(gts[best] - t) <= max_diff:
            gi.append(best); ei.append(i)
    return np.array(gi), np.array(ei)


def umeyama(src: np.ndarray, dst: np.ndarray, with_scale: bool):
    """Umeyama alignment mapping src -> dst; returns s, R, t."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    S = (dst - mu_d).T @ (src - mu_s) / len(src)
    U, D, Vt = np.linalg.svd(S)
    W = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        W[2, 2] = -1
    R = U @ W @ Vt
    s = 1.0
    if with_scale:
        var_s = ((src - mu_s) ** 2).sum() / len(src)
        s = float(np.trace(np.diag(D) @ W) / var_s) if var_s > 0 else 1.0
    t = mu_d - s * R @ mu_s
    return s, R, t


def stats(e: np.ndarray) -> dict:
    if len(e) == 0:
        return dict(rmse=np.nan, mean=np.nan, median=np.nan, std=np.nan, min=np.nan, max=np.nan)
    return dict(rmse=float(np.sqrt(np.mean(e ** 2))), mean=float(e.mean()), median=float(np.median(e)),
                std=float(e.std()), min=float(e.min()), max=float(e.max()))


def builtin_ate_rpe(gt_path, est_path, max_diff: float, delta: int, align: bool, scale: bool):
    gt, est = read_tum(gt_path), read_tum(est_path)
    gi, ei = associate(gt, est, max_diff)
    if len(gi) < 3:
        return stats(np.zeros(0)), stats(np.zeros(0)), stats(np.zeros(0)), int(len(gi))
    G, E = gt[gi], est[ei]
    if align:
        s, R, t = umeyama(E[:, 1:4], G[:, 1:4], scale)
    else:
        s, R, t = 1.0, np.eye(3), np.zeros(3)
    E_t = s * (R @ E[:, 1:4].T).T + t
    ate = np.linalg.norm(G[:, 1:4] - E_t, axis=1)
    rpe_t, rpe_r = [], []
    for k in range(0, len(G) - delta):
        Rg0, Rg1 = quat_to_R(G[k, 4:8]), quat_to_R(G[k + delta, 4:8])
        Re0, Re1 = R @ quat_to_R(E[k, 4:8]), R @ quat_to_R(E[k + delta, 4:8])
        dg = Rg0.T @ (G[k + delta, 1:4] - G[k, 1:4]); de = Re0.T @ (E_t[k + delta] - E_t[k])
        rpe_t.append(np.linalg.norm(dg - de))
        Rrel = (Rg0.T @ Rg1).T @ (Re0.T @ Re1)
        c = np.clip((np.trace(Rrel) - 1) / 2, -1, 1)
        rpe_r.append(np.degrees(np.arccos(c)))
    return stats(ate), stats(np.array(rpe_t)), stats(np.array(rpe_r)), int(len(G))


# ----------------------------------------------------------------------------- evo backend
def evo_stats(kind: str, gt, est, align: bool, scale: bool, delta: int, max_diff: float):
    exe = shutil.which("evo_ape" if kind == "ape" else "evo_rpe")
    if exe is None:
        return None
    with tempfile.TemporaryDirectory() as td:
        z = Path(td) / "res.zip"
        cmd = [exe, "tum", str(gt), str(est), "--t_max_diff", str(max_diff), "--save_results", str(z), "--no_warnings"]
        if align:
            cmd.append("-as" if scale else "-a")
        if kind == "rpe":
            cmd += ["--delta", str(delta), "--delta_unit", "f"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not z.exists():
            return {"_error": (r.stderr or r.stdout)[-400:], "_cmd": " ".join(cmd)}
        with zipfile.ZipFile(z) as zf:
            st = json.loads(zf.read("stats.json"))
        return {k: float(st[k]) for k in ("rmse", "mean", "median", "std", "min", "max") if k in st}


# ----------------------------------------------------------------------------- logs
def parse_log(log_path: Path, patterns: dict) -> dict:
    out = dict(n_landmark_new=0, n_assoc_matched=0, n_assoc_new=0, n_lost=0, n_reloc_try=0, n_reloc_ok=0,
               reloc_ms_median=np.nan, track_ms_mean=np.nan, track_ms_median=np.nan, map_objects_final=np.nan)
    if not log_path.exists():
        return out
    rx = {k: re.compile(v) for k, v in patterns.items() if k != "effective"}
    reloc_ms, frame_ms, last_map = [], [], None
    mean_s = med_s = None
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.rstrip("\n")
            if "landmark_new" in rx and rx["landmark_new"].search(s): out["n_landmark_new"] += 1
            if "assoc_matched" in rx and rx["assoc_matched"].search(s): out["n_assoc_matched"] += 1
            if "assoc_new" in rx and rx["assoc_new"].search(s): out["n_assoc_new"] += 1
            if "lost" in rx and rx["lost"].search(s): out["n_lost"] += 1
            if "reloc" in rx:
                m = rx["reloc"].search(s)
                if m:
                    out["n_reloc_try"] += 1
                    try:
                        if int(m.group(1)) == 1: out["n_reloc_ok"] += 1
                        reloc_ms.append(float(m.group(2)))
                    except Exception:
                        pass
            if "frame_ms" in rx:
                m = rx["frame_ms"].search(s)
                if m:
                    try: frame_ms.append(float(m.group(1)))
                    except Exception: pass
            if "map_objects" in rx:
                m = rx["map_objects"].search(s)
                if m: last_map = int(m.group(1))
            if "mean_track_s" in rx:
                m = rx["mean_track_s"].search(s)
                if m:
                    try: mean_s = float(m.group(1))
                    except Exception: pass
            if "median_track_s" in rx:
                m = rx["median_track_s"].search(s)
                if m:
                    try: med_s = float(m.group(1))
                    except Exception: pass
    if reloc_ms: out["reloc_ms_median"] = float(np.median(reloc_ms))
    if frame_ms:
        out["track_ms_mean"], out["track_ms_median"] = float(np.mean(frame_ms)), float(np.median(frame_ms))
    elif mean_s is not None:
        out["track_ms_mean"] = mean_s * 1000.0
        out["track_ms_median"] = (med_s * 1000.0) if med_s is not None else np.nan
    if last_map is not None: out["map_objects_final"] = last_map
    return out


# ----------------------------------------------------------------------------- object maps
def read_map_objects_txt(path: Path):
    """OA-SLAM map_objects_<name>.txt: 'track_id category_id Q00..Q33' (16 values, column-major dual quadric,
    normalised so that Q(3,3) = -1). Returns [(category, center(3,), axes(3,))]."""
    L = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            v = line.split()
            if len(v) < 18:
                continue
            try:
                cat = v[1]
                Q = np.array([float(x) for x in v[2:18]]).reshape(4, 4, order="F")
                Q = 0.5 * (Q + Q.T)
                if abs(Q[3, 3]) > 1e-12:
                    Q = Q / (-Q[3, 3])
                c = -Q[:3, 3]
                Tc = np.eye(4); Tc[:3, 3] = -c
                Qc = Tc @ Q @ Tc.T
                w = np.linalg.eigvalsh(0.5 * (Qc[:3, :3] + Qc[:3, :3].T))
                axes = np.sqrt(np.abs(w))
                L.append((cat, c, axes))
            except Exception:
                continue
    return L


def count_duplicates(map_path) -> tuple:
    """Duplicates = pairs of same-category landmarks whose centre distance < sum of their largest semi-axes."""
    if map_path is None or not Path(map_path).exists():
        return -1, -1
    try:
        L = read_map_objects_txt(Path(map_path))
    except Exception:
        return -1, -1
    dup = 0
    for i in range(len(L)):
        for j in range(i + 1, len(L)):
            if L[i][0] == L[j][0] and np.linalg.norm(L[i][1] - L[j][1]) < (float(L[i][2].max()) + float(L[j][2].max())):
                dup += 1
    return len(L), dup


# ----------------------------------------------------------------------------- main
def evaluate_run(cfg: dict, seq: str, cname: str, rd: Path, backend: str) -> "dict | None":
    d, ev, pr = cfg["datasets"][seq], cfg["evaluation"], cfg["project"]
    meta_p = rd / "meta.json"
    if not meta_p.exists():
        return None
    meta = read_json(meta_p)
    traj = meta.get("trajectory") or fmt(pr.get("trajectory_for_eval", "camera_poses_{out_name}_tum.txt"), out_name=meta.get("out_name", ""))
    est = rd / traj
    if not est.exists():
        return None
    gt = resolve(cfg, d["gt"])
    align, scale = bool(ev.get("ate_align", True)), bool(ev.get("align_scale", False))
    delta, mdiff, jump_thr = int(ev.get("rpe_delta", 1)), float(ev.get("max_time_diff_s", 0.02)), float(ev.get("jump_threshold_m", 0.5))
    dropped = 0
    if ev.get("drop_identity_poses", True):
        tc = rd / "traj_eval.txt"
        st = write_tracked_copy(est, tc); dropped = st["dropped"]; est = tc
    rot, n_assoc, backend_used = None, None, backend
    ape = rpe = None
    if backend == "evo":
        ape = evo_stats("ape", gt, est, align, scale, delta, mdiff)
        rpe = evo_stats("rpe", gt, est, align, scale, delta, mdiff)
        if ape is None or "_error" in ape or rpe is None or "_error" in rpe:
            log("  evo failed on %s -> builtin fallback (%s)" % (rd, ((ape or {}).get("_error") or (rpe or {}).get("_error") or "")[:120]))
            ape = rpe = None
    if ape is None or rpe is None:
        ape, rpe, rot, n_assoc = builtin_ate_rpe(gt, est, mdiff, delta, align, scale); backend_used = "builtin"
    lg = parse_log(rd / "run.log", ev.get("log_patterns", {}))
    mp = rd / fmt(pr.get("map_objects_file", "map_objects_{out_name}.txt"), out_name=meta.get("out_name", ""))
    n_lm_map, n_dup = count_duplicates(mp)
    rpe_max = rpe.get("max", np.nan)
    row = dict(seq=seq, dataset=d.get("dataset"), set=d.get("set"), cell=cname, run=meta.get("run"), status=meta.get("status"),
               coverage=meta.get("coverage"), dropped_identity_rows=dropped, backend=backend_used,
               ate_rmse=ape["rmse"], ate_mean=ape["mean"], ate_median=ape["median"], ate_std=ape["std"], ate_max=ape["max"],
               rpe_rmse=rpe["rmse"], rpe_mean=rpe["mean"], rpe_median=rpe["median"], rpe_max=rpe_max,
               rpe_rot_rmse=(rot or {}).get("rmse", np.nan) if rot else np.nan,
               jump=int(rpe_max > jump_thr) if rpe_max == rpe_max else 0,
               ate_over_rpe=(ape["rmse"] / rpe["rmse"]) if (rpe["rmse"] and rpe["rmse"] == rpe["rmse"]) else np.nan,
               n_landmarks_map=n_lm_map, n_duplicates=n_dup, wall_s=meta.get("wall_s"))
    row.update(lg)
    row.update({"param_%s" % k: v for k, v in (meta.get("env_overrides") or {}).items()})
    row.update({"eff_%s" % k: v for k, v in (meta.get("effective_from_log") or {}).items()})
    row["effective_mismatch"] = json.dumps(meta.get("effective_mismatch") or {})
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--evo", default=None, help="auto|evo|builtin (overrides config)")
    ap.add_argument("--force", action="store_true", help="re-evaluate runs that already have eval.json")
    a = ap.parse_args()
    cfg = load_config(a.config)
    ev = cfg["evaluation"]
    backend = a.evo or ev.get("evo", "auto")
    if backend == "auto":
        backend = "evo" if shutil.which("evo_ape") else "builtin"
    log("evaluation backend: %s  (align=%s, scale=%s, drop_identity=%s, rpe_delta=%s f)" % (
        backend, ev.get("ate_align", True), ev.get("align_scale", False), ev.get("drop_identity_poses", True), ev.get("rpe_delta", 1)))
    root = results_root(cfg)
    rows = []
    for seq in cfg["datasets"]:
        for cname in cells(cfg):
            for rd in sorted((root / seq / cname).glob("run*")):
                ej = rd / "eval.json"
                if ej.exists() and not a.force:
                    rows.append(read_json(ej)); continue
                row = evaluate_run(cfg, seq, cname, rd, backend)
                if row is None:
                    continue
                write_json(ej, row); rows.append(row)
                log("  %-22s %-12s run%02d ATE=%.4f RPE=%.4f max=%.3f jump=%d lm=%s dup=%s cov=%s" % (
                    seq, cname, row["run"] or 0, row["ate_rmse"], row["rpe_rmse"], row["rpe_max"], row["jump"],
                    row["n_landmarks_map"], row["n_duplicates"], row["coverage"]))
    if not rows:
        log("no completed runs found"); return 1
    keys = []
    for r in rows:
        for k in r:
            if k not in keys: keys.append(k)
    out = root / "oa3_results.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader()
        for r in rows: w.writerow(r)
    log("wrote %s (%d runs)" % (out, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
