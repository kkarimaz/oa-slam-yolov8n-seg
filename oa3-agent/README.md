# oa3-agent — agen AI untuk eksperimen OA-3 (ablasi parameter OA-SLAM-YOLOv8n)

Paket ini menjalankan eksperimen **OA-3** yang diminta Reviewer A ("sensitivity and ablation analyses")
dan Reviewer D ("sensitivity analysis") secara otomatis dan dapat diulang:

```
preflight ─► patch_params (ekspos parameter) ─► smoke test ─► runner (matriks sel × sekuens × N ulangan)
          ─► evaluate (evo: ATE/RPE, jumlah landmark, duplikat, log) ─► report (tabel, gambar, OA3_report.md, zip)
```

Ada dua cara memakainya:

1. **Dengan Claude Code (agen).** Buka terminal di folder ini pada komputer tempat OA-SLAM sudah di-*build*,
   jalankan `claude`, lalu ketik `/oa3-ablation` (atau: "jalankan eksperimen OA-3"). Agen mengikuti prosedur di
   `.claude/skills/oa3-ablation/SKILL.md`: memeriksa konfigurasi, mengekspos parameter (dengan persetujuan Ibu),
   melakukan smoke test, menjalankan matriks, mengevaluasi, dan menyusun laporan. Agen berhenti dan bertanya
   pada setiap gerbang persetujuan (patch kode, rebuild, mulai matriks penuh).
2. **Manual (tanpa Claude Code).** Jalankan perintah-perintah di bagian "Alur manual" di bawah.

Semua angka berasal dari skrip; agen tidak pernah mengarang nilai default maupun metrik.

---

## 1. Persiapan (sekali)

```bash
cd oa3-agent
python3 -m pip install -r requirements.txt        # pyyaml numpy matplotlib evo   (Jetson: tambahkan --user bila perlu)
bash tests/run_mock_pipeline.sh --fast            # uji mandiri ±30 detik dengan OA-SLAM tiruan; harus berakhir "mock pipeline OK"
```

Python ≥ 3.8 (JetPack 5.1 memakai 3.8). `evo` opsional: bila tidak ada, evaluator bawaan dipakai
(hasilnya identik dengan `evo_ape -a` / `evo_rpe --delta 1 --delta_unit f`, sudah diverifikasi sampai 1e-16).

## 2. Yang harus Ibu isi di `oa3_config.yaml`

| Bagian | Isi | Catatan |
|---|---|---|
| `project.oa_slam_root` | folder fork OA-SLAM-YOLOv8n yang sudah di-build | `bin/oa-slam` dan `Vocabulary/ORBvoc.txt` ada di dalamnya |
| `project.arg_template` | urutan argumen executable fork Ibu | Upstream OA-SLAM = 7 argumen (`vocab camera image_list detections reloc_mode output_name show_viewer`). Bila fork Ibu punya argumen `categories_to_ignore_file`, pakai template 8 argumen yang sudah disiapkan (baris komentar). |
| `project.reloc_mode` | `points` / `objects` / `points+objects` | **sama dengan yang dipakai di naskah** |
| `datasets.*` | folder sekuens, `rgb.txt`, `groundtruth.txt`, YAML kamera, JSON deteksi YOLOv8n | JSON deteksi = file yang sama dengan kampanye repeated-run (conf 0.5). `file_name` di JSON harus cocok dengan nama berkas di `rgb.txt` (preflight mengeceknya). |
| `ablation.default` | nilai default parameter di fork Ibu | **jangan ditebak**: jalankan `python3 tools/patch_params.py --root <fork> --check`; nilai yang terdeteksi dari kode dicetak dan disimpan ke `<fork>/oa3_defaults.json`. Upstream: DET_SCORE 0.5, IOU2D 0.2, IOU3D 0.3, TIME_DIFF 30, NB_MATCH 10, MIN_OBS 10, MAP_OBS 40. |
| `ablation.cells` | sel P1/P2/P3 | turunkan dari default: P1 kedua gerbang IoU (longgar: dikurangi ½; ketat: +0,2), P2 `OA_MIN_OBS` ×½ / ×2, P3 kelas *person* (id 0) tidak dipakai sebagai landmark |
| `evaluation` | protokol evaluasi | harus **identik dengan naskah**: berkas trajektori (`camera_poses_*_tum.txt` atau `keyframes_poses_*_tum.txt`), penjajaran SE(3) (`-a`) atau Sim(3) (`-as`), pembuangan pose identitas (frame yang tidak ter-*track* ditulis OA-SLAM sebagai pose identitas) |

## 3. Parameter yang diekspos (`tools/patch_params.py`)

Di OA-SLAM upstream semua parameter asosiasi objek ditulis mati (*hard-coded*) di `src/Tracking.cc`.
Skrip ini mengubahnya menjadi variabel lingkungan tanpa mengubah perilaku default, dan menambah baris log
untuk instrumentasi. Jalankan `--check` (laporan saja), `--diff` (lihat perubahan), `--apply` (terapkan +
cadangan `*.oa3.orig`), `--revert` (kembalikan). Setelah `--apply`, **build ulang** fork.

| Variabel | Baris asal (upstream) | Arti |
|---|---|---|
| `OA_DET_SCORE` | `det->score > 0.5` | gerbang skor deteksi di dalam tracking (tetap 0.5 di OA-3; perlu untuk OA-2 di bawah 0.5) |
| `OA_IOU2D` | `MIN_2D_IOU_THRESH = 0.2` | IoU deteksi vs bbox terakhir track (P1) |
| `OA_IOU3D` | `MIN_3D_IOU_THRESH = 0.3` | IoU deteksi vs proyeksi elipsoid (P1) |
| `OA_TIME_DIFF` | `TIME_DIFF_THRESH = 30` | umur track tanpa observasi (frame) |
| `OA_NB_MATCH` | `THRESHOLD_NB_MATCH = 10` | jumlah map point bersama yang memaksa asosiasi |
| `OA_MIN_OBS` | `GetNbObservations() > 10` | observasi minimum sebelum elipsoid diinisialisasi (P2) |
| `OA_MAP_OBS` | `GetNbObservations() >= 40` | observasi sebelum elipsoid masuk peta |

Baris log yang ditambahkan: `EFFECTIVE k=v` (nilai efektif, dicek otomatis oleh runner — bila tidak sama
dengan yang diminta, run ditandai `effective_mismatch`), `FRAME <i> <ms>`, `ASSOC <frame> matched|new <id>`,
`LANDMARK_NEW <frame> <id> <kelas>`, `LOST <frame>`, `RELOC <frame> <ok> <ms>`.

Bila fork Ibu berbeda dari upstream di baris tertentu, `--check` melaporkan anchor yang tidak ditemukan;
sunting baris padanannya secara manual (format log dipertahankan) — agen Claude Code akan membantu dan
meminta persetujuan sebelum menyunting.

## 4. Alur manual

```bash
python3 -m oa3.preflight --config oa3_config.yaml                 # semua PROBLEM harus hilang
python3 tools/patch_params.py --root /path/OA-SLAM-YOLOv8n --check  # lalu --diff, --apply, build ulang
# smoke test: 1 run sel default pada sekuens kontrol, lalu 1 run P1_tight (EFFECTIVE harus berubah)
python3 -m oa3.runner   --config oa3_config.yaml --only-seqs bonn_crowd --only-cells default,P1_tight --runs 1
python3 -m oa3.evaluate --config oa3_config.yaml
# matriks penuh (dapat dilanjutkan bila terputus: jalankan lagi perintah yang sama)
nohup python3 -m oa3.runner --config oa3_config.yaml > runner.out 2>&1 &
tail -f runner.out
python3 -m oa3.evaluate --config oa3_config.yaml
python3 -m oa3.report   --config oa3_config.yaml --zip
```

Perkiraan waktu: OA-SLAM memutar sekuens pada laju sensor (tidur bila lebih cepat dari waktu nyata), jadi tiap
run ≈ durasi sekuens + ±20 s pemuatan kosakata. Untuk 4 sekuens × 6 sel × 3 ulangan = 72 run, sekitar 3–4 jam
(fr2_desk_with_person yang panjang mendominasi). Akurasi OA-3 tidak bergantung pada platform, jadi jalankan di
workstation lab; Jetson cukup untuk OA-1.

## 5. Keluaran (`results_root`, default `results_oa3/`)

| Berkas | Isi |
|---|---|
| `<sekuens>/<sel>/runNN/` | `run.log`, `meta.json` (perintah, env, md5 JSON deteksi, git HEAD, coverage, nilai EFFECTIVE), `eval.json`, `camera_poses_*_tum.txt`, `keyframes_poses_*_tum.txt`, `map_objects_*.txt`, ... |
| `oa3_results.csv` | satu baris per run: ATE/RPE (RMSE, mean, median, max), lonjakan (RPE satu langkah > 0,5 m), jumlah landmark & pasangan duplikat (dari kuadrik dual `map_objects_*.txt`), penghitung log, waktu tracking, parameter yang diminta dan yang di-echo |
| `oa3_cell_summary.csv`, `oa3_summary.json` | agregat per sekuens × sel: mean ± SD, median, rentang, Δ % vs default, pemisahan rentang run, cek sekuens kontrol |
| `fig_oa3_ate.png`, `fig_oa3_rpe.png`, `fig_oa3_map.png` | gambar sensitivitas per keluarga parameter (mean ± SD; sekuens kontrol abu-abu putus-putus) dan statistik peta |
| `OA3_report.md` | laporan lengkap + paragraf draf untuk naskah (bagian 7) |
| `oa3_handoff_<tanggal>.zip` | semua di atas untuk dilampirkan ke revisi |
| `platform.json`, `config_used.yaml` | platform dan konfigurasi kampanye (untuk pernyataan reprodusibilitas) |

Angka dari `OA3_report.md` bagian 4 mengisi paragraf sensitivitas/ablasi di naskah dan baris "pending"
pada *Response to Reviewer A* dan *Response to Reviewer D*.

## 6. Catatan metodologis yang harus diputuskan Ibu

1. **Identitas evaluasi.** Upstream OA-SLAM menulis *semua* frame ke `camera_poses_<nama>_tum.txt`; frame yang
   tidak ter-*track* ditulis sebagai pose identitas (0 0 0 0 0 0 1). `drop_identity_poses: true` membuangnya
   sebelum evo. Bila kampanye repeated-run dievaluasi dengan cara lain (mis. `keyframes_poses_*_tum.txt`, atau
   tanpa membuang pose identitas), samakan di `evaluation:` lalu `python3 -m oa3.evaluate ... --force`.
2. **Penjajaran.** Naskah memakai Umeyama SE(3) (`evo_ape -a`). OA-SLAM upstream berjalan MONOCULAR, sehingga
   sebagian peneliti memakai Sim(3) (`-as`); paket ini mengikuti naskah (`align_scale: false`). Jangan diubah
   di tengah kampanye.
3. **Sel default vs OA-2.** Bila sel default sudah ada dari kampanye OA-2 (conf 0.5) dengan konfigurasi dan
   platform yang **sama persis**, `include_default_cell: false` menghemat 12 run; bila ragu, biarkan `true`.
4. **Sekuens kontrol** (`bonn_crowd`, reprodusibel ±2 % pada kampanye 5 run): perubahan median ATE > 25 % pada
   sel mana pun akan ditandai — periksa `LOST`/`RELOC`/`jump` di log sebelum menafsirkan.

## 7. Uji mandiri

`bash tests/run_mock_pipeline.sh` (≈2 menit; `--fast` ≈30 detik) membuat dataset sintetis kecil dan
OA-SLAM tiruan (`tools/mock_oa_slam.py`) yang meniru CLI, tata letak berkas keluaran dan baris log versi
upstream yang sudah dipatch, lalu menjalankan seluruh alur (termasuk uji *resume* dan *retry*). Angkanya tidak
bermakna ilmiah — hanya membuktikan alurnya bekerja.
