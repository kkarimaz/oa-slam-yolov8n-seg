"""Shared helpers for the OA-3 ablation agent: config loading, path resolution, cells, logging.

Python >= 3.8 (Jetson JetPack 5.x ships 3.8). No dependency besides PyYAML here.
"""
from __future__ import annotations
import hashlib, json, os, platform, shutil, subprocess, sys, time
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required: pip install pyyaml")


# ----------------------------------------------------------------------------- config / paths
def load_config(path) -> dict:
    path = Path(path).resolve()
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_config_path"] = str(path)
    cfg["_base"] = str(path.parent)
    cfg.setdefault("project", {}); cfg.setdefault("datasets", {}); cfg.setdefault("ablation", {})
    cfg.setdefault("execution", {}); cfg.setdefault("evaluation", {})
    return cfg


def resolve(cfg: dict, p) -> "Path | None":
    """Resolve a path relative to the config file location (absolute paths and ~ pass through)."""
    if p is None or str(p).strip() == "":
        return None
    q = Path(os.path.expanduser(str(p)))
    return q if q.is_absolute() else (Path(cfg["_base"]) / q).resolve()


def resolve_in_root(cfg: dict, p) -> "Path | None":
    """Resolve a path relative to project.oa_slam_root (used for executable, vocabulary, ignore files)."""
    if p is None or str(p).strip() == "":
        return None
    q = Path(os.path.expanduser(str(p)))
    if q.is_absolute():
        return q
    root = resolve(cfg, cfg["project"].get("oa_slam_root")) or Path(cfg["_base"])
    return (root / q).resolve()


def results_root(cfg: dict) -> Path:
    r = resolve(cfg, cfg["execution"].get("results_root", "results_oa3"))
    r.mkdir(parents=True, exist_ok=True)
    return r


def fmt(template, **fields) -> str:
    """Format a template such as 'camera_poses_{out_name}_tum.txt' (missing fields are left as-is)."""
    if template is None:
        return ""
    class _D(dict):
        def __missing__(self, k):
            return "{" + k + "}"
    return str(template).format_map(_D(fields))


# ----------------------------------------------------------------------------- experimental cells
def cells(cfg: dict) -> dict:
    """All experimental cells: name -> {env, ignore_file, min_score, drop_categories}."""
    ab = cfg["ablation"]
    out = {}
    if ab.get("include_default_cell", True):
        out[ab.get("default_cell_name", "default")] = {"env": {}, "ignore_file": None, "min_score": None, "drop_categories": None}
    for name, spec in (ab.get("cells") or {}).items():
        spec = dict(spec or {})
        out[name] = {
            "ignore_file": spec.pop("ignore_file", None),
            "min_score": spec.pop("min_score", None),
            "drop_categories": spec.pop("drop_categories", None),
            "env": {k: str(v) for k, v in spec.items()},
        }
    return out


def effective_env(cfg: dict, cell: dict) -> dict:
    """Environment variables passed to the executable: defaults of the fork, overridden by the cell."""
    env = {k: str(v) for k, v in (cfg["ablation"].get("default") or {}).items()}
    env.update(cell.get("env") or {})
    return env


def families(cfg: dict) -> dict:
    """Parameter families for the report: name -> {param, cells:[...], labels:[...]}. Derived if absent."""
    fam = cfg["ablation"].get("families")
    if fam:
        return {k: dict(v) for k, v in fam.items()}
    default = cfg["ablation"].get("default_cell_name", "default")
    out = {}
    for name, cell in cells(cfg).items():
        if name == default:
            continue
        key = "/".join(sorted(cell["env"].keys())) if cell["env"] else "detections"
        out.setdefault(key, {"param": key, "cells": [default], "labels": ["default"]})
        out[key]["cells"].append(name); out[key]["labels"].append(name)
    return out


# ----------------------------------------------------------------------------- misc
def md5(path) -> "str | None":
    if path is None or not Path(path).exists():
        return None
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_hash(repo) -> "str | None":
    if repo is None or not Path(repo).exists():
        return None
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo), stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None


def count_lines(path) -> int:
    """Non-empty, non-comment lines (rgb.txt / associations.txt style)."""
    if path is None or not Path(path).exists():
        return 0
    n = 0
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                n += 1
    return n


def is_identity_pose(vals) -> bool:
    """TUM row [t x y z qx qy qz qw]: OA-SLAM writes the identity pose for frames that were not tracked."""
    try:
        x, y, z, qx, qy, qz, qw = [float(v) for v in vals[1:8]]
    except Exception:
        return False
    return abs(x) < 1e-12 and abs(y) < 1e-12 and abs(z) < 1e-12 and abs(qx) < 1e-12 and abs(qy) < 1e-12 and abs(qz) < 1e-12 and abs(qw - 1.0) < 1e-9


def trajectory_stats(path) -> dict:
    """Rows / tracked (non-identity) rows of a TUM trajectory file."""
    rows, tracked = 0, 0
    if path is None or not Path(path).exists():
        return {"rows": 0, "tracked": 0}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            v = s.replace(",", " ").split()
            if len(v) < 8:
                continue
            rows += 1
            if not is_identity_pose(v):
                tracked += 1
    return {"rows": rows, "tracked": tracked}


def platform_info() -> dict:
    info = {"node": platform.node(), "machine": platform.machine(), "python": platform.python_version(),
            "uname": " ".join(platform.uname()), "nproc": os.cpu_count(), "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    for cmd, key in ((["nvpmodel", "-q"], "nvpmodel"), (["cat", "/etc/nv_tegra_release"], "tegra_release"),
                     (["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"], "nvidia_smi"),
                     (["lscpu"], "lscpu")):
        if shutil.which(cmd[0]) is None and cmd[0] != "cat":
            continue
        try:
            info[key] = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=10).strip()[:2000]
        except Exception:
            pass
    return info


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def write_json(path, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False, default=str)


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
