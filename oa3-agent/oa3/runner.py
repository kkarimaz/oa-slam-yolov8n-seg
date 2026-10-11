"""Run the OA-3 ablation matrix: cells x sequences x repeated runs, interleaved, resumable.

Usage:
  python -m oa3.runner --config oa3_config.yaml [--dry-run] [--mock] [--only-cells A,B] [--only-seqs s1,s2] [--runs N]

Each run gets its own folder  <results_root>/<sequence>/<cell>/runNN/  containing
  run.log (stdout+stderr of the executable), meta.json, and everything the run wrote into <cwd>/<out_name>/
  (camera_poses_<out_name>_tum.txt, keyframes_poses_..., map_objects_....txt, ...).
A run is skipped on re-invocation when meta.json reports exit_code 0 and the trajectory exists (resume).
Never run two instances at the same time: OA-SLAM replays sequences at sensor rate and both would share the CPU.
"""
from __future__ import annotations
import argparse, json, os, re, shutil, signal, subprocess, sys, time
from pathlib import Path
from .common import (load_config, resolve, resolve_in_root, results_root, cells, effective_env, fmt, md5, git_hash,
                     count_lines, trajectory_stats, platform_info, log, write_json, read_json)


# ----------------------------------------------------------------------------- plan
def build_plan(cfg: dict, only_cells=None, only_seqs=None, runs=None):
    C = cells(cfg)
    if only_cells:
        C = {k: v for k, v in C.items() if k in only_cells}
    seqs = list(cfg["datasets"].keys())
    if only_seqs:
        seqs = [s for s in seqs if s in only_seqs]
    N = int(runs or cfg["ablation"].get("runs_per_cell", 3))
    plan = []
    if cfg["execution"].get("interleave", True):
        for s in seqs:
            for i in range(1, N + 1):
                for c in C:
                    plan.append((s, c, i))
    else:
        for c in C:
            for s in seqs:
                for i in range(1, N + 1):
                    plan.append((s, c, i))
    return plan, C


def run_dir(cfg: dict, seq: str, cell: str, i: int) -> Path:
    return results_root(cfg) / seq / cell / ("run%02d" % i)


def out_name(seq: str, cell: str, i: int) -> str:
    return "%s__%s__run%02d" % (seq, cell, i)


def is_done(rd: Path) -> bool:
    m = rd / "meta.json"
    if not m.exists():
        return False
    try:
        meta = read_json(m)
    except Exception:
        return False
    traj = meta.get("trajectory")
    return meta.get("exit_code") == 0 and bool(traj) and (rd / traj).exists() and meta.get("status") in ("ok", "low_coverage")


def parse_effective(log_path: Path, pattern: str) -> dict:
    out = {}
    if not log_path.exists():
        return out
    rx = re.compile(pattern)
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = rx.search(line)
            if m and len(m.groups()) >= 2:
                out[m.group(1)] = m.group(2)
    return out


# ----------------------------------------------------------------------------- detection-side cells
def filtered_detections(cfg: dict, seq: str, cname: str, cell: dict) -> Path:
    """Return the detection JSON to use for this cell (filtered copy for min_score / drop_categories cells)."""
    src = resolve(cfg, cfg["datasets"][seq]["det_json"])
    if cell.get("min_score") is None and not cell.get("drop_categories"):
        return src
    from .filter_detections import filter_file
    dst_dir = results_root(cfg) / "_detections"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / ("%s__%s.json" % (seq, cname))
    if not dst.exists():
        st = filter_file(src, dst, min_score=cell.get("min_score"), drop_categories=cell.get("drop_categories"))
        log("filtered detections for %s/%s: kept %d of %d detections -> %s" % (seq, cname, st["kept"], st["total"], dst))
    return dst


# ----------------------------------------------------------------------------- one run
def execute(cfg: dict, seq: str, cname: str, cell: dict, i: int, mock: bool, dry: bool) -> dict:
    pr, ex = cfg["project"], cfg["execution"]
    d = cfg["datasets"][seq]
    root = resolve(cfg, pr.get("oa_slam_root")) or Path(cfg["_base"])
    rd = run_dir(cfg, seq, cname, i)
    if is_done(rd):
        return {"seq": seq, "cell": cname, "run": i, "status": "skipped (done)"}
    rd.mkdir(parents=True, exist_ok=True)

    exe = resolve_in_root(cfg, pr.get("executable"))
    voc = resolve_in_root(cfg, pr.get("vocabulary"))
    ign = resolve_in_root(cfg, cell.get("ignore_file") or pr.get("ignore_file"))
    det = filtered_detections(cfg, seq, cname, cell) if not dry else resolve(cfg, d["det_json"])
    on = out_name(seq, cname, i)
    fields = dict(exe=str(exe or ""), vocab=str(voc or ""), yaml=str(resolve(cfg, d.get("yaml")) or ""),
                  seq_dir=str(resolve(cfg, d.get("seq_dir")) or ""), frames_list=str(resolve(cfg, d.get("frames_list")) or ""),
                  det_json=str(det or ""), ignore_file=str(ign or ""), reloc_mode=str(pr.get("reloc_mode", "points")),
                  out_name=on, show_viewer=str(pr.get("show_viewer", 0)))
    cmd = fmt(pr["arg_template"], **fields)
    if mock:
        mock_py = Path(__file__).resolve().parent.parent / "tools" / "mock_oa_slam.py"
        cmd = "%s %s %s" % (sys.executable, mock_py, cmd.split(" ", 1)[1] if " " in cmd else "")
    cwd = rd if str(ex.get("cwd", "oa_slam_root")) == "run_dir" else root
    env = dict(os.environ)
    eff = effective_env(cfg, cell)
    env.update(eff)
    env["OA3_RUN_DIR"] = str(rd)
    env["OA3_OUT_NAME"] = on

    meta = dict(seq=seq, dataset=d.get("dataset"), set=d.get("set"), cell=cname, run=i, out_name=on, cmd=cmd, cwd=str(cwd),
                env_overrides=eff, cell_spec={k: v for k, v in cell.items() if k != "env"},
                det_json=str(det), det_md5=md5(det), git_head=git_hash(root), started=time.strftime("%Y-%m-%d %H:%M:%S"))
    if dry:
        log("DRY  %-22s %-12s run%02d  env=%s" % (seq, cname, i, eff))
        return {"seq": seq, "cell": cname, "run": i, "status": "dry"}

    # remove stale outputs so that a crash cannot be mistaken for a result
    sub = fmt(pr.get("output_subdir", "{out_name}"), out_name=on)
    if sub:
        shutil.rmtree(cwd / sub, ignore_errors=True)
    for fn in pr.get("output_files") or []:
        try:
            (cwd / fmt(fn, out_name=on)).unlink()
        except FileNotFoundError:
            pass

    log("RUN  %-22s %-12s run%02d  env=%s" % (seq, cname, i, eff))
    t0 = time.time()
    with open(rd / "run.log", "w", encoding="utf-8") as lf:
        lf.write("# cmd: %s\n# cwd: %s\n# env: %s\n" % (cmd, cwd, json.dumps(eff)))
        lf.flush()
        try:
            # start_new_session=True puts the shell (shell=True's direct child) and everything
            # it spawns (the real oa-slam process) in their own process group.
            proc = subprocess.Popen(cmd, shell=True, cwd=str(cwd), env=env, stdout=lf, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            code = proc.wait(timeout=int(ex.get("timeout_s", 2400)))
        except subprocess.TimeoutExpired:
            # subprocess.run()/Popen.kill() only signal the direct child (the shell with
            # shell=True); the real oa-slam process is left running and orphaned. Observed
            # directly: a "timed out" run's oa-slam process was still alive and burning 100%
            # CPU 9+ hours later, and further runs piled up the same way, pushing the machine
            # into heavy swapping. Kill the whole process group instead.
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait()
            code = -9
            lf.write("\n[oa3] TIMEOUT after %s s (process group killed)\n" % ex.get("timeout_s", 2400))
    wall = time.time() - t0

    # collect outputs: <cwd>/<out_name>/* and any flat files
    if sub and (cwd / sub).is_dir() and (cwd / sub).resolve() != rd.resolve():
        for p in (cwd / sub).iterdir():
            shutil.move(str(p), str(rd / p.name))
        shutil.rmtree(cwd / sub, ignore_errors=True)
    for fn in pr.get("output_files") or []:
        src = cwd / fmt(fn, out_name=on)
        if src.exists():
            shutil.move(str(src), str(rd / src.name))

    traj = fmt(pr.get("trajectory_for_eval", "camera_poses_{out_name}_tum.txt"), out_name=on)
    frames = count_lines(resolve(cfg, d.get("frames_list")))
    ts = trajectory_stats(rd / traj)
    coverage = (ts["tracked"] / frames) if frames else None
    status = "ok" if (code == 0 and (rd / traj).exists()) else "failed"
    if status == "ok" and coverage is not None and coverage < float(ex.get("min_frame_coverage", 0.9)):
        status = "low_coverage"
    eff_log = parse_effective(rd / "run.log", cfg["evaluation"].get("log_patterns", {}).get("effective", r"^EFFECTIVE\s+(\w+)\s*=\s*(\S+)"))
    # sanity: the executable must echo the values we asked for (otherwise the parameter is NOT exposed)
    mismatch = {k: (v, eff_log.get(k)) for k, v in eff.items() if k in eff_log and abs(float(eff_log[k]) - float(v)) > 1e-9} if eff_log else {}
    meta.update(exit_code=code, wall_s=round(wall, 1), frames=frames, trajectory=traj, trajectory_rows=ts["rows"],
                tracked_rows=ts["tracked"], coverage=None if coverage is None else round(coverage, 4), status=status,
                effective_from_log=eff_log, effective_mismatch=mismatch, finished=time.strftime("%Y-%m-%d %H:%M:%S"))
    write_json(rd / "meta.json", meta)
    log("     -> %s exit=%s wall=%.0fs coverage=%s effective=%s%s" % (
        status, code, wall, "n/a" if coverage is None else round(coverage, 3), eff_log,
        "  !! MISMATCH %s" % mismatch if mismatch else ""))
    if not mock:
        time.sleep(float(ex.get("sleep_between_runs_s", 5)))
    return {"seq": seq, "cell": cname, "run": i, "status": status}


# ----------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    ap.add_argument("--mock", action="store_true", help="use tools/mock_oa_slam.py instead of the real executable")
    ap.add_argument("--only-cells", default=None, help="comma-separated cell names")
    ap.add_argument("--only-seqs", default=None, help="comma-separated sequence names")
    ap.add_argument("--runs", type=int, default=None, help="override ablation.runs_per_cell")
    a = ap.parse_args()
    cfg = load_config(a.config)
    plan, C = build_plan(cfg, a.only_cells.split(",") if a.only_cells else None,
                         a.only_seqs.split(",") if a.only_seqs else None, a.runs)
    rr = results_root(cfg)
    log("plan: %d runs over %d cells x %d sequences; results -> %s" % (len(plan), len(C), len({p[0] for p in plan}), rr))
    if not a.dry_run:
        pi = rr / "platform.json"
        if not pi.exists():
            write_json(pi, platform_info())
        shutil.copy(cfg["_config_path"], rr / "config_used.yaml")
    results = []
    for (s, c, i) in plan:
        results.append(execute(cfg, s, c, C[c], i, a.mock, a.dry_run))
    if cfg["execution"].get("retry_failed_once", True) and not a.dry_run:
        for r in list(results):
            if r["status"] == "failed":
                log("RETRY %s %s run%02d" % (r["seq"], r["cell"], r["run"]))
                rd = run_dir(cfg, r["seq"], r["cell"], r["run"])
                shutil.rmtree(rd, ignore_errors=True)
                results.append(execute(cfg, r["seq"], r["cell"], C[r["cell"]], r["run"], a.mock, False))
    summary = {}
    for r in results:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    log("summary: " + ", ".join("%s=%d" % (k, v) for k, v in summary.items()))
    write_json(rr / "runner_summary.json", {"plan_size": len(plan), "results": results, "summary": summary,
                                            "finished": time.strftime("%Y-%m-%d %H:%M:%S")})
    return 0 if summary.get("failed", 0) == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
