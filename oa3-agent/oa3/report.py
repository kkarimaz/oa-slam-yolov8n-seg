"""Aggregate the OA-3 results: per-cell statistics, deltas vs. the default cell, control-sequence check,
sensitivity figures, a Markdown report and (optionally) a hand-off zip.

Usage:  python -m oa3.report --config oa3_config.yaml [--zip]
Reads   <results_root>/oa3_results.csv  (written by oa3.evaluate)
Writes  oa3_cell_summary.csv, oa3_summary.json, fig_oa3_ate.png, fig_oa3_rpe.png, fig_oa3_map.png, OA3_report.md
"""
from __future__ import annotations
import argparse, csv, json, math, sys, time, zipfile
from pathlib import Path
import numpy as np
from .common import load_config, results_root, cells, families, effective_env, log, read_json, write_json

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#8e5bd6", "#d63384", "#b8860b"]
CONTROL_COLOR = "#7a7f87"


# ----------------------------------------------------------------------------- helpers
def fnum(x):
    try:
        v = float(x)
        return v if v == v else None
    except Exception:
        return None


def load_rows(path: Path) -> list:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def agg(vals: list) -> dict:
    v = np.array([x for x in vals if x is not None], float)
    if len(v) == 0:
        return dict(n=0, mean=None, sd=None, median=None, min=None, max=None)
    return dict(n=int(len(v)), mean=float(v.mean()), sd=float(v.std(ddof=1)) if len(v) > 1 else 0.0,
                median=float(np.median(v)), min=float(v.min()), max=float(v.max()))


def fmt_ms(a: dict, digits=4) -> str:
    if not a or a.get("mean") is None:
        return "–"
    return ("%%.%df ± %%.%df" % (digits, digits)) % (a["mean"], a["sd"] or 0.0)


def fmt_rng(a: dict, digits=4) -> str:
    if not a or a.get("mean") is None:
        return ""
    return ("[%%.%df, %%.%df]" % (digits, digits)) % (a["min"], a["max"])


def pct(new, ref):
    if new is None or ref in (None, 0):
        return None
    return 100.0 * (new - ref) / ref


def fmt_pct(p):
    return "–" if p is None else ("%+.1f %%" % p)


# ----------------------------------------------------------------------------- aggregation
def summarize(cfg: dict, rows: list) -> dict:
    ab = cfg["ablation"]
    default = ab.get("default_cell_name", "default")
    C = list(cells(cfg).keys())
    seqs = list(cfg["datasets"].keys())
    used = [r for r in rows if r.get("status") in ("ok", "low_coverage")]
    per = {}
    for s in seqs:
        per[s] = {}
        for c in C:
            R = [r for r in used if r["seq"] == s and r["cell"] == c]
            if not R:
                continue
            e = {
                "n": len(R),
                "n_low_coverage": sum(1 for r in R if r.get("status") == "low_coverage"),
                "ate": agg([fnum(r.get("ate_rmse")) for r in R]),
                "rpe": agg([fnum(r.get("rpe_rmse")) for r in R]),
                "rpe_max": agg([fnum(r.get("rpe_max")) for r in R]),
                "jumps": int(sum(int(fnum(r.get("jump")) or 0) for r in R)),
                "coverage": agg([fnum(r.get("coverage")) for r in R]),
                "landmarks": agg([fnum(r.get("n_landmarks_map")) for r in R if fnum(r.get("n_landmarks_map")) not in (None, -1)]),
                "duplicates": agg([fnum(r.get("n_duplicates")) for r in R if fnum(r.get("n_duplicates")) not in (None, -1)]),
                "landmark_new": agg([fnum(r.get("n_landmark_new")) for r in R]),
                "assoc_matched": agg([fnum(r.get("n_assoc_matched")) for r in R]),
                "assoc_new": agg([fnum(r.get("n_assoc_new")) for r in R]),
                "lost": agg([fnum(r.get("n_lost")) for r in R]),
                "reloc_ok": agg([fnum(r.get("n_reloc_ok")) for r in R]),
                "track_ms": agg([fnum(r.get("track_ms_mean")) for r in R]),
                "wall_s": agg([fnum(r.get("wall_s")) for r in R]),
                "effective": sorted(set(", ".join("%s=%s" % (k[4:], v) for k, v in sorted(r.items()) if k.startswith("eff_") and v) for r in R)),
                "mismatch": sorted(set(r.get("effective_mismatch", "{}") for r in R if r.get("effective_mismatch", "{}") not in ("", "{}"))),
            }
            per[s][c] = e
        # deltas vs default
        d0 = per[s].get(default)
        for c, e in per[s].items():
            if d0 is None or c == default:
                e["d_ate_pct"] = None; e["d_rpe_pct"] = None; e["ate_ranges_overlap"] = None
                continue
            e["d_ate_pct"] = pct(e["ate"]["mean"], d0["ate"]["mean"])
            e["d_rpe_pct"] = pct(e["rpe"]["mean"], d0["rpe"]["mean"])
            e["d_ate_abs"] = None if e["ate"]["mean"] is None or d0["ate"]["mean"] is None else e["ate"]["mean"] - d0["ate"]["mean"]
            if e["ate"]["min"] is not None and d0["ate"]["min"] is not None:
                e["ate_ranges_overlap"] = not (e["ate"]["min"] > d0["ate"]["max"] or e["ate"]["max"] < d0["ate"]["min"])
            else:
                e["ate_ranges_overlap"] = None

    # per family: mean relative change over dynamic sequences, count of separated ranges
    fam_out = {}
    ctrl_seq = ab.get("control_sequence")
    dyn = [s for s in seqs if cfg["datasets"][s].get("set", "dynamic") == "dynamic" and s != ctrl_seq]
    for fname, fam in families(cfg).items():
        fo = {"param": fam.get("param"), "cells": fam.get("cells"), "labels": fam.get("labels"), "per_cell": {}}
        for c in fam.get("cells", []):
            if c == default:
                continue
            ds = [per[s][c]["d_ate_pct"] for s in dyn if c in per.get(s, {}) and per[s][c].get("d_ate_pct") is not None]
            dr = [per[s][c]["d_rpe_pct"] for s in dyn if c in per.get(s, {}) and per[s][c].get("d_rpe_pct") is not None]
            sep = [s for s in dyn if c in per.get(s, {}) and per[s][c].get("ate_ranges_overlap") is False]
            worse = [s for s in dyn if c in per.get(s, {}) and (per[s][c].get("d_ate_pct") or 0) > 0]
            fo["per_cell"][c] = {"mean_d_ate_pct": float(np.mean(ds)) if ds else None, "mean_d_rpe_pct": float(np.mean(dr)) if dr else None,
                                 "n_seq": len(ds), "n_ate_ranges_separated": len(sep), "seq_ranges_separated": sep,
                                 "n_seq_worse": len(worse), "max_abs_d_ate_pct": float(np.max(np.abs(ds))) if ds else None}
        fam_out[fname] = fo

    # control check
    ctrl, tol = ab.get("control_sequence"), float(ab.get("control_tolerance_rel", 0.25))
    control = {"sequence": ctrl, "tolerance_rel": tol, "cells": {}, "ok": None}
    if ctrl and ctrl in per and default in per[ctrl] and per[ctrl][default]["ate"]["median"]:
        ref = per[ctrl][default]["ate"]["median"]
        flags = []
        for c, e in per[ctrl].items():
            if c == default or e["ate"]["median"] is None:
                continue
            rel = abs(e["ate"]["median"] - ref) / ref
            control["cells"][c] = {"rel_change": rel, "flag": rel > tol}
            if rel > tol:
                flags.append(c)
        control["ok"] = len(flags) == 0
        control["flagged_cells"] = flags
        control["note"] = ("control sequence stable" if not flags else
                           "control sequence moved by more than %.0f %% in cells %s: the parameter does affect this sequence "
                           "or the setup drifted; inspect run logs before interpreting" % (100 * tol, ", ".join(flags)))

    # completeness
    N = int(ab.get("runs_per_cell", 3))
    planned = len(seqs) * len(C) * N
    counts = {}
    for r in rows:
        counts[r.get("status")] = counts.get(r.get("status"), 0) + 1
    completeness = {"planned": planned, "evaluated": len(rows), "by_status": counts,
                    "missing": [(s, c, N - len([r for r in used if r["seq"] == s and r["cell"] == c])) for s in seqs for c in C
                                if len([r for r in used if r["seq"] == s and r["cell"] == c]) < N]}
    return {"default_cell": default, "cells": C, "sequences": seqs, "per_sequence": per, "families": fam_out,
            "control": control, "completeness": completeness, "generated": time.strftime("%Y-%m-%d %H:%M:%S")}


# ----------------------------------------------------------------------------- figures
def sensitivity_figure(cfg: dict, S: dict, metric: str, ylabel: str, out: Path, digits=3):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fams = families(cfg)
    per, seqs = S["per_sequence"], S["sequences"]
    ctrl = cfg["ablation"].get("control_sequence")
    n = max(1, len(fams))
    fig, axes = plt.subplots(1, n, figsize=(4.6 * n, 3.9), squeeze=False)
    colors = {}
    k = 0
    for s in seqs:
        if s == ctrl:
            colors[s] = CONTROL_COLOR
        else:
            colors[s] = PALETTE[k % len(PALETTE)]; k += 1
    for ax, (fname, fam) in zip(axes[0], fams.items()):
        cs, labels = fam.get("cells", []), fam.get("labels") or fam.get("cells", [])
        x = np.arange(len(cs))
        for s in seqs:
            y = [per.get(s, {}).get(c, {}).get(metric, {}).get("mean") for c in cs]
            e = [per.get(s, {}).get(c, {}).get(metric, {}).get("sd") or 0.0 for c in cs]
            if all(v is None for v in y):
                continue
            yy = np.array([np.nan if v is None else v for v in y], float)
            ax.errorbar(x, yy, yerr=e, marker="o", ms=5, lw=1.6, capsize=3, color=colors[s],
                        ls="--" if s == ctrl else "-", label=s + (" (control)" if s == ctrl else ""))
        ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=8)
        ax.set_title("%s\n(%s)" % (fname, fam.get("param", "")), fontsize=9)
        ax.set_xlabel("parameter value", fontsize=8)
        ax.grid(True, axis="y", lw=0.4, alpha=0.5)
        ax.tick_params(axis="y", labelsize=8)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0][0].set_ylabel(ylabel, fontsize=9)
    handles, labels_ = axes[0][0].get_legend_handles_labels()
    if not handles:
        for ax in axes[0]:
            handles, labels_ = ax.get_legend_handles_labels()
            if handles:
                break
    fig.legend(handles, labels_, loc="lower center", ncol=min(4, max(1, len(labels_))), fontsize=8, frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("OA-3 sensitivity: %s (mean ± SD over %s runs)" % (ylabel, cfg["ablation"].get("runs_per_cell", 3)), fontsize=10)
    fig.tight_layout(rect=(0, 0.08, 1, 0.95))
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def map_figure(cfg: dict, S: dict, out: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    per, seqs, C = S["per_sequence"], S["sequences"], S["cells"]
    ctrl = cfg["ablation"].get("control_sequence")
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9))
    for ax, key, title in zip(axes, ("landmarks", "duplicates"), ("object landmarks in final map", "duplicate landmark pairs")):
        w = 0.8 / max(1, len(seqs))
        k = 0
        for j, s in enumerate(seqs):
            y = [per.get(s, {}).get(c, {}).get(key, {}).get("mean") for c in C]
            e = [per.get(s, {}).get(c, {}).get(key, {}).get("sd") or 0.0 for c in C]
            yy = np.array([np.nan if v is None else v for v in y], float)
            col = CONTROL_COLOR if s == ctrl else PALETTE[k % len(PALETTE)]
            if s != ctrl:
                k += 1
            ax.bar(np.arange(len(C)) + (j - (len(seqs) - 1) / 2) * w, yy, width=w, yerr=e, capsize=2, color=col, label=s)
        ax.set_xticks(np.arange(len(C))); ax.set_xticklabels(C, fontsize=8, rotation=20)
        ax.set_title(title, fontsize=9); ax.grid(True, axis="y", lw=0.4, alpha=0.5)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    axes[0].set_ylabel("count (mean ± SD)", fontsize=9)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=min(4, max(1, len(l))), fontsize=8, frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------------------- markdown
def write_markdown(cfg: dict, S: dict, root: Path, out: Path, figs: list):
    ab = cfg["ablation"]
    default = S["default_cell"]
    per = S["per_sequence"]
    L = []
    L.append("# OA-3 parameter-sensitivity (ablation) report — OA-SLAM-YOLOv8n\n")
    L.append("Generated %s from `%s`.\n" % (S["generated"], root / "oa3_results.csv"))
    pi = root / "platform.json"
    if pi.exists():
        p = read_json(pi)
        L.append("**Platform:** %s, %s, %s CPU threads, Python %s%s\n" % (
            p.get("node"), p.get("machine"), p.get("nproc"), p.get("python"),
            ("; nvpmodel: `%s`" % p.get("nvpmodel", "").splitlines()[0]) if p.get("nvpmodel") else ""))
    L.append("**Design:** one-factor-at-a-time around the default configuration; %s repeated runs per cell; "
             "sequences %s; control sequence `%s` (tolerance ±%.0f %%).\n" % (
                 ab.get("runs_per_cell", 3), ", ".join("`%s`" % s for s in S["sequences"]), ab.get("control_sequence"),
                 100 * float(ab.get("control_tolerance_rel", 0.25))))
    L.append("**Evaluation:** ATE RMSE after %s alignment%s; RPE RMSE over %s frame(s); untracked frames %s; backend evo/builtin as recorded per run.\n" % (
        "SE(3) Umeyama" if not cfg["evaluation"].get("align_scale") else "Sim(3) Umeyama",
        "" if cfg["evaluation"].get("ate_align", True) else " (NO alignment)",
        cfg["evaluation"].get("rpe_delta", 1), "dropped" if cfg["evaluation"].get("drop_identity_poses", True) else "kept"))

    # cells
    L.append("\n## 1. Cells and effective parameters\n")
    L.append("| cell | variables passed | echoed by the executable (`EFFECTIVE`) | detection filter |")
    L.append("|---|---|---|---|")
    for cname, cell in cells(cfg).items():
        env = effective_env(cfg, cell)
        eff = set()
        mism = set()
        for s in S["sequences"]:
            e = per.get(s, {}).get(cname)
            if e:
                eff.update(e["effective"]); mism.update(e["mismatch"])
        flt = []
        if cell.get("min_score") is not None: flt.append("min_score=%s" % cell["min_score"])
        if cell.get("drop_categories"): flt.append("drop_categories=%s" % cell["drop_categories"])
        if cell.get("ignore_file"): flt.append("ignore_file=%s" % cell["ignore_file"])
        L.append("| `%s` | %s | %s%s | %s |" % (cname, ", ".join("%s=%s" % kv for kv in env.items()) or "(defaults)",
                                              "; ".join(sorted(eff)) or "(no EFFECTIVE lines in log)",
                                              " **MISMATCH %s**" % "; ".join(sorted(mism)) if mism else "", ", ".join(flt) or "–"))
    if any(per.get(s, {}).get(c, {}).get("mismatch") for s in S["sequences"] for c in S["cells"]):
        L.append("\n> **Warning:** at least one run echoed a parameter value different from the one requested. "
                 "The parameter exposure is not working for that variable; those cells are not valid.")

    # completeness
    cp = S["completeness"]
    L.append("\n## 2. Completeness\n")
    L.append("Planned %d runs; evaluated %d; by status: %s." % (cp["planned"], cp["evaluated"],
             ", ".join("%s=%d" % kv for kv in cp["by_status"].items()) or "–"))
    if cp["missing"]:
        L.append("\nMissing runs: " + ", ".join("%s/%s (%d)" % m for m in cp["missing"]))

    # control
    ct = S["control"]
    L.append("\n## 3. Control-sequence check (`%s`)\n" % ct.get("sequence"))
    if ct.get("ok") is None:
        L.append("Control sequence not evaluated (missing default cell or results).")
    else:
        L.append("| cell | median ATE change vs default | flag |")
        L.append("|---|---|---|")
        for c, v in ct["cells"].items():
            L.append("| `%s` | %+.1f %% | %s |" % (c, 100 * v["rel_change"] * (1 if per[ct["sequence"]][c]["ate"]["median"] >= per[ct["sequence"]][default]["ate"]["median"] else -1),
                                              "**> tolerance**" if v["flag"] else "ok"))
        L.append("\n" + ct.get("note", ""))

    # per family tables
    L.append("\n## 4. Results per parameter family\n")
    for fname, fam in S["families"].items():
        L.append("\n### %s — `%s`\n" % (fname, fam.get("param")))
        L.append("| sequence | cell | n | ATE RMSE (m) mean ± SD | range | Δ vs default | ranges separated | RPE RMSE (m) | jumps | landmarks | duplicates | lost | track ms |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s in S["sequences"]:
            for c, lab in zip(fam.get("cells", []), fam.get("labels") or fam.get("cells", [])):
                e = per.get(s, {}).get(c)
                if not e:
                    L.append("| %s | `%s` (%s) | 0 | – | | | | | | | | | |" % (s, c, lab)); continue
                sep = e.get("ate_ranges_overlap")
                L.append("| %s | `%s` (%s) | %d%s | %s | %s | %s | %s | %s | %d | %s | %s | %s | %s |" % (
                    s, c, lab, e["n"], (" (%d low cov.)" % e["n_low_coverage"]) if e["n_low_coverage"] else "",
                    fmt_ms(e["ate"]), fmt_rng(e["ate"]), fmt_pct(e.get("d_ate_pct")),
                    "–" if sep is None else ("**yes**" if sep is False else "no"),
                    fmt_ms(e["rpe"]), e["jumps"], fmt_ms(e["landmarks"], 1), fmt_ms(e["duplicates"], 1), fmt_ms(e["lost"], 1), fmt_ms(e["track_ms"], 1)))
        fo = fam.get("per_cell", {})
        if fo:
            L.append("\nMean relative change of ATE over the dynamic sequences, control excluded (vs `%s`):" % default)
            for c, v in fo.items():
                L.append("- `%s`: ATE %s (max |Δ| %s), RPE %s; ATE run-ranges separated from the default in %d/%d sequences%s; worse than default in %d/%d." % (
                    c, fmt_pct(v["mean_d_ate_pct"]), fmt_pct(v["max_abs_d_ate_pct"]), fmt_pct(v["mean_d_rpe_pct"]),
                    v["n_ate_ranges_separated"], v["n_seq"], (" (%s)" % ", ".join(v["seq_ranges_separated"])) if v["seq_ranges_separated"] else "",
                    v["n_seq_worse"], v["n_seq"]))

    # figures
    L.append("\n## 5. Figures\n")
    for f in figs:
        L.append("![%s](%s)\n" % (f.name, f.name))

    # reading guide
    L.append("\n## 6. How to read the result (guide, not a verdict)\n")
    L.append("- With n = %s runs per cell no formal test is attempted; a parameter is reported as *influential* on a sequence only when "
             "the run-ranges of the cell and of the default do not overlap **and** the change exceeds the run-to-run spread of the default." % ab.get("runs_per_cell", 3))
    L.append("- A change on the control sequence larger than the tolerance means the parameter also affects a sequence that is normally "
             "reproducible: check whether the effect is systematic (all runs) before calling it a sensitivity.")
    L.append("- Compare the *size* of the parameter effect with the paradigm gap reported in the manuscript (OA-SLAM ≈ 4× the ATE of YSLAMv8n on "
             "dynamic sequences): if every cell stays far above the mask-filtering systems, the ranking is robust to the tuning of these parameters.")
    L.append("- `jumps` counts runs whose single-step RPE exceeds %s m (relocalisation jump / map reset); `duplicates` counts same-class landmark pairs "
             "whose centres are closer than the sum of their largest semi-axes." % cfg["evaluation"].get("jump_threshold_m", 0.5))

    # manuscript paragraph
    L.append("\n## 7. Draft paragraph for the manuscript (edit before use)\n")
    fams = S["families"]
    parts = []
    for fname, fam in fams.items():
        for c, v in fam.get("per_cell", {}).items():
            if v["mean_d_ate_pct"] is None:
                continue
            parts.append("%s (%s → `%s`) changed the mean ATE by %s on the dynamic sequences (run-ranges separated from the default in %d/%d sequences)" % (
                fam.get("param"), default, c, fmt_pct(v["mean_d_ate_pct"]), v["n_ate_ranges_separated"], v["n_seq"]))
    L.append("> To assess whether the accuracy gap of OA-SLAM-YOLOv8n could be attributed to its parameterisation rather than to the "
             "landmark paradigm, a one-factor-at-a-time sensitivity analysis was performed around the default configuration "
             "(%s runs per cell, %s). %s. "
             "The control sequence (%s) %s. [Conclude here whether every cell remains above the mask-filtering systems.]" % (
                 ab.get("runs_per_cell", 3), ", ".join(S["sequences"]), "; ".join(parts) if parts else "[results pending]",
                 ct.get("sequence"), "remained within ±%.0f %% of its default value" % (100 * float(ab.get("control_tolerance_rel", 0.25))) if ct.get("ok") else "changed by more than the tolerance in cells %s" % ", ".join(ct.get("flagged_cells", [])) if ct.get("ok") is not None else "[not evaluated]"))

    L.append("\n## 8. Files\n")
    L.append("- `oa3_results.csv` — one row per run (raw metrics, log counters, parameters echoed by the executable)")
    L.append("- `oa3_cell_summary.csv`, `oa3_summary.json` — aggregated statistics used in this report")
    L.append("- `<sequence>/<cell>/runNN/` — run.log, meta.json, eval.json, trajectories and object maps of every run")
    L.append("- `config_used.yaml`, `platform.json` — configuration and platform of the campaign")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def write_cell_csv(S: dict, out: Path):
    cols = ["seq", "cell", "n", "n_low_coverage", "ate_mean", "ate_sd", "ate_median", "ate_min", "ate_max", "d_ate_pct", "ate_ranges_overlap",
            "rpe_mean", "rpe_sd", "rpe_median", "d_rpe_pct", "rpe_max_mean", "jumps", "coverage_mean", "landmarks_mean", "landmarks_sd",
            "duplicates_mean", "landmark_new_mean", "assoc_matched_mean", "assoc_new_mean", "lost_mean", "reloc_ok_mean", "track_ms_mean", "wall_s_mean"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(cols)
        for s, cs in S["per_sequence"].items():
            for c, e in cs.items():
                w.writerow([s, c, e["n"], e["n_low_coverage"], e["ate"]["mean"], e["ate"]["sd"], e["ate"]["median"], e["ate"]["min"], e["ate"]["max"],
                            e.get("d_ate_pct"), e.get("ate_ranges_overlap"), e["rpe"]["mean"], e["rpe"]["sd"], e["rpe"]["median"], e.get("d_rpe_pct"),
                            e["rpe_max"]["mean"], e["jumps"], e["coverage"]["mean"], e["landmarks"]["mean"], e["landmarks"]["sd"], e["duplicates"]["mean"],
                            e["landmark_new"]["mean"], e["assoc_matched"]["mean"], e["assoc_new"]["mean"], e["lost"]["mean"], e["reloc_ok"]["mean"],
                            e["track_ms"]["mean"], e["wall_s"]["mean"]])


def make_zip(root: Path, out: Path):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            if p.is_file() and p != out and not p.name.endswith(".zip"):
                if p.suffix in (".obj", ".yaml", ".json", ".txt", ".csv", ".md", ".png", ".log") or p.name in ("meta.json", "eval.json"):
                    if p.suffix == ".yaml" and p.name.startswith("map_"):
                        continue   # reloadable osmap dumps can be large; not needed for the paper
                    if p.suffix == ".obj":
                        continue
                    z.write(p, p.relative_to(root))


# ----------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--zip", action="store_true", help="also write oa3_handoff_<date>.zip with everything needed for the paper")
    a = ap.parse_args()
    cfg = load_config(a.config)
    root = results_root(cfg)
    res = root / "oa3_results.csv"
    if not res.exists():
        log("missing %s - run  python -m oa3.evaluate  first" % res); return 1
    rows = load_rows(res)
    S = summarize(cfg, rows)
    write_json(root / "oa3_summary.json", S)
    write_cell_csv(S, root / "oa3_cell_summary.csv")
    figs = []
    try:
        f1 = root / "fig_oa3_ate.png"; sensitivity_figure(cfg, S, "ate", "ATE RMSE (m)", f1); figs.append(f1)
        f2 = root / "fig_oa3_rpe.png"; sensitivity_figure(cfg, S, "rpe", "RPE RMSE (m)", f2); figs.append(f2)
        f3 = root / "fig_oa3_map.png"; map_figure(cfg, S, f3); figs.append(f3)
    except Exception as e:  # matplotlib missing or headless problems must not block the report
        log("figure generation failed: %s" % e)
    md = root / "OA3_report.md"
    write_markdown(cfg, S, root, md, figs)
    log("wrote %s, %s, %s%s" % (md.name, "oa3_summary.json", "oa3_cell_summary.csv", (", " + ", ".join(f.name for f in figs)) if figs else ""))
    ct = S["control"]
    if ct.get("ok") is False:
        log("CONTROL CHECK: " + ct.get("note", ""))
    if a.zip:
        z = root / ("oa3_handoff_%s.zip" % time.strftime("%Y%m%d_%H%M"))
        make_zip(root, z)
        log("wrote %s (%.1f MB)" % (z, z.stat().st_size / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
