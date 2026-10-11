#!/usr/bin/env python3
"""Expose the hard-coded OA-SLAM object-association parameters as environment variables and add the
OA-3 log instrumentation (EFFECTIVE / FRAME / ASSOC / LANDMARK_NEW / LOST / RELOC lines).

The anchors below match upstream OA-SLAM (Inria 2022, src/Tracking.cc). Numeric literals are captured
from YOUR sources, so the generated header keeps the true defaults of your fork.

Usage:
  python tools/patch_params.py --root /path/to/OA-SLAM-YOLOv8n --check     # report anchors + detected defaults (no change)
  python tools/patch_params.py --root ... --diff                              # show the unified diff
  python tools/patch_params.py --root ... --apply                             # write changes (+ .oa3.orig backups)
  python tools/patch_params.py --root ... --revert                            # restore backups
Then rebuild the fork (cd build && make -j) and run a smoke test.

Exit code: 0 = every anchor found exactly once (or already applied); 1 = some anchor missing/ambiguous.
"""
from __future__ import annotations
import argparse, difflib, glob, json, os, re, shutil, sys
from pathlib import Path

HEADER_NAME = "include/oa3_params.h"

# (id, file_key, regex, replacement (function of match), env_var or None, expected_count)
# file_key: "tracking" -> src/Tracking.cc ; "tracking_h" -> include/Tracking.h ; "main" -> the .cc holding the main loop
ANCHORS = [
    ("include_header", "tracking", r'^#include "Tracking.h"[ \t]*$',
     lambda m: '#include "Tracking.h"\n#include "oa3_params.h"', None),
    ("det_score", "tracking",
     r'if \(det->score > (?P<v>[0-9.]+)\) \{\n(?P<body>(?:.*\n){0,3}?)(?P<push>[ \t]*current_frame_good_detections_\.push_back\(det\);)',
     lambda m: 'if (det->score > oa3::P().det_score) {\n' + m.group("body") + m.group("push"), "OA_DET_SCORE"),
    ("iou2d", "tracking", r'double MIN_2D_IOU_THRESH = (?P<v>[0-9.]+);',
     lambda m: 'double MIN_2D_IOU_THRESH = oa3::P().iou2d;', "OA_IOU2D"),
    ("iou3d", "tracking", r'double MIN_3D_IOU_THRESH = (?P<v>[0-9.]+);',
     lambda m: 'double MIN_3D_IOU_THRESH = oa3::P().iou3d;', "OA_IOU3D"),
    ("time_diff", "tracking", r'int TIME_DIFF_THRESH = (?P<v>[0-9]+);',
     lambda m: 'int TIME_DIFF_THRESH = oa3::P().time_diff;', "OA_TIME_DIFF"),
    ("time_diff_literal", "tracking", r'tr->GetLastObsFrameId\(\) \+ (?P<v>[0-9]+) >= current_frame_idx_',
     lambda m: 'tr->GetLastObsFrameId() + TIME_DIFF_THRESH >= current_frame_idx_', None),
    ("nb_match", "tracking", r'int THRESHOLD_NB_MATCH = (?P<v>[0-9]+);',
     lambda m: 'int THRESHOLD_NB_MATCH = oa3::P().nb_match;', "OA_NB_MATCH"),
    ("min_obs", "tracking", r'tr->GetNbObservations\(\) > (?P<v>[0-9]+) && tr->GetStatus\(\) == ObjectTrackStatus::ONLY_2D',
     lambda m: 'tr->GetNbObservations() > oa3::P().min_obs && tr->GetStatus() == ObjectTrackStatus::ONLY_2D', "OA_MIN_OBS"),
    ("map_obs", "tracking", r'tr->GetNbObservations\(\) >= (?P<v>[0-9]+) && tr->GetStatus\(\) == ObjectTrackStatus::INITIALIZED',
     lambda m: 'tr->GetNbObservations() >= oa3::P().map_obs && tr->GetStatus() == ObjectTrackStatus::INITIALIZED', "OA_MAP_OBS"),
    ("log_landmark_new", "tracking", r'^(?P<ind>[ \t]*)tr->InsertInMap\(mpMap\);[ \t]*$',
     lambda m: m.group("ind") + 'std::printf("LANDMARK_NEW %lu %u %u\\n", (unsigned long)current_frame_idx_, (unsigned)tr->GetId(), (unsigned)tr->GetCategoryId()); std::fflush(stdout);\n'
               + m.group("ind") + 'tr->InsertInMap(mpMap);', None),
    ("log_assoc_matched", "tracking", r'^(?P<ind>[ \t]*)associated_track->AddDetection\(det->bbox, det->score, Rt, current_frame_idx_, kf\);[ \t]*$',
     lambda m: m.group("ind") + 'std::printf("ASSOC %lu matched %u\\n", (unsigned long)current_frame_idx_, (unsigned)associated_track->GetId());\n'
               + m.group("ind") + 'associated_track->AddDetection(det->bbox, det->score, Rt, current_frame_idx_, kf);', None),
    ("log_assoc_new", "tracking", r'^(?P<ind>[ \t]*)new_tracks\.push_back\(tr\);[ \t]*$',
     lambda m: m.group("ind") + 'new_tracks.push_back(tr);\n'
               + m.group("ind") + 'std::printf("ASSOC %lu new %u\\n", (unsigned long)current_frame_idx_, (unsigned)tr->GetId());', None),
    ("log_lost", "tracking", r'^(?P<ind>[ \t]*)mState=LOST;[ \t]*$',
     lambda m: m.group("ind") + '{ mState=LOST; std::printf("LOST %lu\\n", (unsigned long)current_frame_idx_); std::fflush(stdout); }', None),
    ("reloc_wrapper", "tracking", r'^bool Tracking::Relocalization\(\)\n\{',
     lambda m: ('bool Tracking::Relocalization()\n{\n'
                '    auto oa3_t1 = std::chrono::steady_clock::now();\n'
                '    bool oa3_ok = RelocalizationImpl();\n'
                '    double oa3_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - oa3_t1).count();\n'
                '    std::printf("RELOC %lu %d %.3f\\n", (unsigned long)current_frame_idx_, oa3_ok ? 1 : 0, oa3_ms); std::fflush(stdout);\n'
                '    return oa3_ok;\n'
                '}\n\n'
                'bool Tracking::RelocalizationImpl()\n{'), None),
    ("reloc_decl", "tracking_h", r'^(?P<ind>[ \t]*)bool Relocalization\(\);[ \t]*$',
     lambda m: m.group("ind") + 'bool Relocalization();\n' + m.group("ind") + 'bool RelocalizationImpl();', None),
    ("main_include", "main", r'^#include[ \t]*<iostream>[ \t]*$',
     lambda m: '#include<iostream>\n#include <cstdio>', None),
    ("log_frame", "main", r'^(?P<ind>[ \t]*)vTimesTrack\[ni\][ \t]*=[ \t]*ttrack;[ \t]*$',
     lambda m: m.group("ind") + 'vTimesTrack[ni]=ttrack;\n'
               + m.group("ind") + 'std::printf("FRAME %d %.3f\\n", ni, ttrack * 1000.0); std::fflush(stdout);', None),
]

ENV_DEFAULT_FALLBACK = {"OA_DET_SCORE": "0.5", "OA_IOU2D": "0.2", "OA_IOU3D": "0.3", "OA_TIME_DIFF": "30",
                        "OA_NB_MATCH": "10", "OA_MIN_OBS": "10", "OA_MAP_OBS": "40"}


def header_text(defaults: dict) -> str:
    d = dict(ENV_DEFAULT_FALLBACK); d.update(defaults)
    return '''// oa3_params.h - OA-SLAM object-association parameters exposed as environment variables.
// Generated by oa3-agent/tools/patch_params.py. Defaults below were read from the source at patch time.
// Unset variables keep the defaults, so the unpatched behaviour is reproduced exactly.
#pragma once
#include <cstdio>
#include <cstdlib>
#include <chrono>

namespace oa3 {
inline double env_double(const char* name, double def) { const char* v = std::getenv(name); return (v && *v) ? std::atof(v) : def; }
inline int    env_int(const char* name, int def)       { const char* v = std::getenv(name); return (v && *v) ? std::atoi(v) : def; }

struct Params {
    double det_score;   // detection score gate inside tracking            (OA_DET_SCORE, default %(OA_DET_SCORE)s)
    double iou2d;       // MIN_2D_IOU_THRESH: IoU with the track's last bbox (OA_IOU2D,     default %(OA_IOU2D)s)
    double iou3d;       // MIN_3D_IOU_THRESH: IoU with projected ellipsoid  (OA_IOU3D,     default %(OA_IOU3D)s)
    int    time_diff;   // TIME_DIFF_THRESH: frames before a track expires  (OA_TIME_DIFF, default %(OA_TIME_DIFF)s)
    int    nb_match;    // THRESHOLD_NB_MATCH: shared map points            (OA_NB_MATCH,  default %(OA_NB_MATCH)s)
    int    min_obs;     // observations before ellipsoid initialisation     (OA_MIN_OBS,   default %(OA_MIN_OBS)s)
    int    map_obs;     // observations before insertion into the map       (OA_MAP_OBS,   default %(OA_MAP_OBS)s)
    Params()
        : det_score(env_double("OA_DET_SCORE", %(OA_DET_SCORE)s)), iou2d(env_double("OA_IOU2D", %(OA_IOU2D)s)),
          iou3d(env_double("OA_IOU3D", %(OA_IOU3D)s)), time_diff(env_int("OA_TIME_DIFF", %(OA_TIME_DIFF)s)),
          nb_match(env_int("OA_NB_MATCH", %(OA_NB_MATCH)s)), min_obs(env_int("OA_MIN_OBS", %(OA_MIN_OBS)s)),
          map_obs(env_int("OA_MAP_OBS", %(OA_MAP_OBS)s)) {
        std::printf("EFFECTIVE OA_DET_SCORE=%%g\\nEFFECTIVE OA_IOU2D=%%g\\nEFFECTIVE OA_IOU3D=%%g\\nEFFECTIVE OA_TIME_DIFF=%%d\\n"
                    "EFFECTIVE OA_NB_MATCH=%%d\\nEFFECTIVE OA_MIN_OBS=%%d\\nEFFECTIVE OA_MAP_OBS=%%d\\n",
                    det_score, iou2d, iou3d, time_diff, nb_match, min_obs, map_obs);
        std::fflush(stdout);
    }
};
inline const Params& P() { static Params p; return p; }
}  // namespace oa3
''' % d


def find_main_cc(root: Path) -> "Path | None":
    cands = [Path(p) for pat in ("Examples/*.cc", "Examples/**/*.cc", "src/*.cc", "*.cc", "apps/*.cc", "examples/*.cc")
             for p in glob.glob(str(root / pat), recursive=True)]
    for p in cands:
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # upstream pre-sizes vTimesTrack and assigns by index; some forks (e.g. oa-slam-yolov8n-seg)
        # reserve() + push_back() instead, which is equivalent for a loop that processes frames in
        # strict order -- accept either spelling so main-loop detection works on both.
        if (re.search(r'vTimesTrack\[ni\][ \t]*=[ \t]*ttrack;', t)
                or re.search(r'vTimesTrack\.push_back\(ttrack\);', t)) \
                and ("show_AR_viewer" in t or "TrackMonocular" in t):
            return p
    return None


def files_for(root: Path) -> dict:
    return {"tracking": root / "src" / "Tracking.cc", "tracking_h": root / "include" / "Tracking.h", "main": find_main_cc(root)}


def analyse(root: Path):
    F = files_for(root)
    texts = {}
    for k, p in F.items():
        texts[k] = p.read_text(encoding="utf-8", errors="ignore") if (p and p.exists()) else None
    report, defaults, new_texts = [], {}, dict(texts)
    already = texts.get("tracking") is not None and '#include "oa3_params.h"' in texts["tracking"]
    # text that proves an anchor was already applied (so that a second --apply never double-patches)
    PROBE = {"include_header": '#include "oa3_params.h"', "det_score": 'oa3::P().det_score', "iou2d": 'oa3::P().iou2d',
             "iou3d": 'oa3::P().iou3d', "time_diff": 'oa3::P().time_diff', "time_diff_literal": 'GetLastObsFrameId() + TIME_DIFF_THRESH',
             "nb_match": 'oa3::P().nb_match', "min_obs": 'oa3::P().min_obs', "map_obs": 'oa3::P().map_obs',
             "log_landmark_new": '"LANDMARK_NEW %lu', "log_assoc_matched": '"ASSOC %lu matched', "log_assoc_new": '"ASSOC %lu new',
             "log_lost": '"LOST %lu', "reloc_wrapper": 'Tracking::RelocalizationImpl()', "reloc_decl": 'bool RelocalizationImpl();',
             "main_include": '#include <cstdio>', "log_frame": '"FRAME %d'}
    for aid, fk, rx, repl, env in ANCHORS:
        t = new_texts.get(fk)
        if t is None:
            report.append((aid, fk, "FILE MISSING", None)); continue
        if PROBE.get(aid) and PROBE[aid] in t:
            report.append((aid, fk, "already applied", None)); continue
        pat = re.compile(rx, re.M)
        ms = list(pat.finditer(t))
        if len(ms) == 1:
            m = ms[0]
            if env and "v" in m.groupdict() and m.group("v") is not None:
                defaults[env] = m.group("v")
            new_texts[fk] = t[:m.start()] + repl(m) + t[m.end():]
            report.append((aid, fk, "found", m.group("v") if (env and "v" in m.groupdict()) else None))
        elif len(ms) == 0:
            report.append((aid, fk, "NOT FOUND", None))
        else:
            report.append((aid, fk, "AMBIGUOUS (%d matches)" % len(ms), None))
    return F, texts, new_texts, report, defaults, already


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="OA-SLAM fork root (contains src/Tracking.cc, include/Tracking.h)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true"); g.add_argument("--diff", action="store_true")
    g.add_argument("--apply", action="store_true"); g.add_argument("--revert", action="store_true")
    ap.add_argument("--defaults-out", default=None, help="write detected defaults as JSON (default: <root>/oa3_defaults.json)")
    a = ap.parse_args()
    root = Path(a.root).expanduser().resolve()
    if not root.exists():
        print("root not found:", root); return 1
    F = files_for(root)

    if a.revert:
        n = 0
        for p in list(F.values()) + [root / HEADER_NAME]:
            if p is None:
                continue
            b = Path(str(p) + ".oa3.orig")
            if b.exists():
                shutil.copy(b, p); b.unlink(); n += 1; print("restored", p)
        h = root / HEADER_NAME
        if h.exists():
            h.unlink(); print("removed", h)
        print("reverted %d file(s)" % n); return 0

    F, texts, new_texts, report, defaults, already = analyse(root)
    print("OA-SLAM root : %s" % root)
    for k, p in F.items():
        print("  %-10s : %s%s" % (k, p, "" if (p and p.exists()) else "   <-- MISSING"))
    print("\nanchors:")
    ok = True
    for aid, fk, status, v in report:
        print("  %-20s %-10s %-22s %s" % (aid, fk, status, ("default = " + v) if v else ""))
        if status.startswith(("NOT FOUND", "AMBIGUOUS", "FILE MISSING")):
            ok = False
    if defaults:
        print("\ndetected defaults (put them in ablation.default of oa3_config.yaml):")
        for k, v in defaults.items():
            print("  %s: %s" % (k, v))
        out = Path(a.defaults_out) if a.defaults_out else root / "oa3_defaults.json"
        try:
            out.write_text(json.dumps(defaults, indent=1))
            print("  -> written to %s" % out)
        except Exception as e:
            print("  (could not write defaults file: %s)" % e)
    if not ok:
        print("\nSome anchors were not found exactly once. Your fork differs from upstream at those places:\n"
              "open src/Tracking.cc, locate the equivalent lines and patch them by hand (keep the EFFECTIVE/LOG formats),\n"
              "or extend ANCHORS in tools/patch_params.py. Do NOT run --apply until every anchor is 'found' or 'already applied'.")
    if a.diff:
        for fk, p in F.items():
            if p is None or texts.get(fk) is None or new_texts[fk] == texts[fk]:
                continue
            sys.stdout.writelines(difflib.unified_diff(texts[fk].splitlines(True), new_texts[fk].splitlines(True),
                                                       fromfile=str(p), tofile=str(p) + " (patched)"))
        print("\n--- new file: %s ---" % HEADER_NAME)
        print(header_text(defaults))
    if a.apply:
        if not ok:
            print("refusing to apply: fix the anchors first."); return 1
        for fk, p in F.items():
            if p is None or texts.get(fk) is None or new_texts[fk] == texts[fk]:
                continue
            b = Path(str(p) + ".oa3.orig")
            if not b.exists():
                shutil.copy(p, b)
            p.write_text(new_texts[fk], encoding="utf-8")
            print("patched", p, "(backup: %s)" % b.name)
        h = root / HEADER_NAME
        h.parent.mkdir(parents=True, exist_ok=True)
        if h.exists() and not defaults:
            print("kept existing", h, "(defaults captured at first patch time)")
        else:
            h.write_text(header_text(defaults), encoding="utf-8")
            print("wrote", h)
        print("\nNext: rebuild the fork (e.g.  cd %s/build && make -j$(nproc) ), then run the smoke test:\n"
              "  OA_IOU2D=0.2 ./bin/oa-slam ... 2>&1 | grep -m 7 EFFECTIVE" % root)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
