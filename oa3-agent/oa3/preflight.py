"""Preflight checks: verify every path, tool and parameter default before any run is started.

Usage:  python -m oa3.preflight --config oa3_config.yaml [--mock]
Exit code 0 = ready; 1 = blocking problems found.
"""
from __future__ import annotations
import argparse, json, re, shutil, sys
from pathlib import Path
from .common import (load_config, resolve, resolve_in_root, cells, effective_env, families, count_lines, git_hash, log)


def check_detections_json(path: Path, frames_list: Path) -> list:
    """Cheap structural check of the detection JSON against the image list."""
    notes = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return ["cannot parse detection JSON: %s" % e]
    frames = data if isinstance(data, list) else data.get("frames")
    if not isinstance(frames, list) or not frames:
        return ["detection JSON is not a list of frames"]
    f0 = frames[0]
    for k in ("file_name", "detections"):
        if k not in f0:
            notes.append("detection JSON frames lack key '%s'" % k)
    dets = [d for fr in frames[:200] for d in fr.get("detections", [])]
    if dets:
        d0 = dets[0]
        for k in ("category_id", "detection_score", "bbox"):
            if k not in d0:
                notes.append("detections lack key '%s'" % k)
    # file-name overlap with the image list
    names = set(Path(str(fr.get("file_name", ""))).name for fr in frames)
    listed = []
    with open(frames_list, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                parts = s.split()
                listed.append(Path(parts[-1]).name)
    if listed:
        hit = sum(1 for n in listed if n in names)
        if hit == 0:
            notes.append("none of the %d listed images has an entry in the detection JSON (file_name mismatch?)" % len(listed))
        elif hit < 0.9 * len(listed):
            notes.append("only %d of %d listed images have detections entries" % (hit, len(listed)))
    return notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--mock", action="store_true", help="skip executable checks (mock pipeline)")
    a = ap.parse_args()
    cfg = load_config(a.config)
    problems, warnings = [], []

    pr = cfg["project"]
    root = resolve(cfg, pr.get("oa_slam_root"))
    if not a.mock:
        if root is None or not root.exists():
            problems.append("oa_slam_root not found: %s" % root)
        exe = resolve_in_root(cfg, pr.get("executable"))
        if exe is None or not exe.exists():
            problems.append("executable not found: %s" % exe)
        voc = resolve_in_root(cfg, pr.get("vocabulary"))
        if voc is None or not voc.exists():
            problems.append("vocabulary not found: %s" % voc)
        ign = resolve_in_root(cfg, pr.get("ignore_file"))
        if pr.get("ignore_file") and (ign is None or not ign.exists()):
            problems.append("default ignore_file not found: %s" % ign)
        if "{ignore_file}" in pr.get("arg_template", "") and not pr.get("ignore_file"):
            warnings.append("arg_template uses {ignore_file} but project.ignore_file is empty (an empty argument will be passed)")
        log("git HEAD of fork: %s" % git_hash(root))
        # is the parameter exposure in place?  (tools/patch_params.py adds include/oa3_params.h)
        if root and root.exists():
            hdr = root / "include" / "oa3_params.h"
            if not hdr.exists():
                problems.append("include/oa3_params.h not found in the fork: parameters are NOT exposed yet. "
                                "Run  python tools/patch_params.py --root %s --check  (then --apply, then rebuild)" % root)
    if pr.get("reloc_mode") not in ("points", "objects", "points+objects"):
        warnings.append("reloc_mode '%s' is not one of points|objects|points+objects (fine only if your fork differs)" % pr.get("reloc_mode"))

    for name, d in cfg["datasets"].items():
        for key in ("seq_dir", "frames_list", "gt", "yaml", "det_json"):
            p = resolve(cfg, d.get(key))
            if p is None or not p.exists():
                problems.append("[%s] %s missing: %s" % (name, key, p))
        fr = resolve(cfg, d.get("frames_list"))
        if fr and fr.exists():
            n = count_lines(fr)
            log("[%s] %s %s frames=%d" % (name, d.get("dataset"), d.get("set"), n))
            if n < 100:
                warnings.append("[%s] only %d frames listed in %s" % (name, n, fr))
            dj = resolve(cfg, d.get("det_json"))
            if dj and dj.exists():
                for note in check_detections_json(dj, fr):
                    warnings.append("[%s] %s" % (name, note))

    ab = cfg["ablation"]
    for k, v in (ab.get("default") or {}).items():
        if v is None or str(v).strip() in ("", "TODO", "?"):
            problems.append("default value for %s is a placeholder; fill in the true default of your fork" % k)
    default = ab.get("default_cell_name", "default")
    C = cells(cfg)
    for cname, cell in C.items():
        env = effective_env(cfg, cell)
        ign = cell.get("ignore_file")
        if ign:
            p = resolve_in_root(cfg, ign)
            if p is None or not p.exists():
                problems.append("[cell %s] ignore_file missing: %s" % (cname, p))
        for k in cell["env"]:
            if k not in (ab.get("default") or {}):
                warnings.append("[cell %s] variable %s has no entry in ablation.default (the fork's default is unknown)" % (cname, k))
        log("cell %-12s env=%s ignore_file=%s min_score=%s drop=%s" % (cname, env, ign, cell.get("min_score"), cell.get("drop_categories")))
    for fname, fam in families(cfg).items():
        for c in fam.get("cells", []):
            if c not in C:
                problems.append("[family %s] cell '%s' is not defined" % (fname, c))
        if default not in fam.get("cells", []):
            warnings.append("[family %s] does not contain the default cell '%s'" % (fname, default))
    ctrl = ab.get("control_sequence")
    if ctrl and ctrl not in cfg["datasets"]:
        warnings.append("control_sequence '%s' is not in datasets" % ctrl)

    ev = cfg["evaluation"].get("evo", "auto")
    has_evo = shutil.which("evo_ape") is not None
    if ev == "evo" and not has_evo:
        problems.append("evaluation.evo=evo but evo_ape is not on PATH (pip install evo)")
    if ev == "auto":
        log("evaluation backend: " + ("evo (found on PATH)" if has_evo else "builtin (evo_ape not found)"))
    for k, v in (cfg["evaluation"].get("log_patterns") or {}).items():
        try:
            re.compile(v)
        except re.error as e:
            problems.append("log_patterns.%s is not a valid regex: %s" % (k, e))

    n_runs = len(cfg["datasets"]) * len(C) * int(ab.get("runs_per_cell", 3))
    log("planned runs: %d sequences x %d cells x %s runs = %d" % (len(cfg["datasets"]), len(C), ab.get("runs_per_cell", 3), n_runs))

    for w in warnings:
        log("WARNING: " + w)
    for p in problems:
        log("PROBLEM: " + p)
    if problems:
        log("preflight FAILED - fix the problems above before running")
        return 1
    log("preflight OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
