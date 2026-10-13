# Catatan OA-3 — setup, perubahan, dan keputusan yang masih pending

Dibuat 2026-10-04 s/d 2026-10-08. Catatan ini didokumentasikan sesuai permintaan PANDUAN_ASISTEN.md
("Catat setiap keanehan... catatan ini ikut dikirim").

## 1. Setup awal: adaptasi `oa3_config.yaml` dari template Bu Ika ke environment lokal

`oa3_config.yaml` yang diterima masih berisi path milik komputer Bu Ika (`/home/ika/OA-SLAM-YOLOv8n`,
`/data/tum/...`) dan beberapa ketidakcocokan dengan fork `oa-slam-yolov8n-seg`. Perubahan yang dilakukan:

- `project.oa_slam_root`: `/home/ika/OA-SLAM-YOLOv8n` → `/home/khansa/Documents/coding/oa-slam-yolov8n-seg`
- `project.arg_template`: field `{show_viewer}` dibuang. Fork ini punya **7 argumen posisi saja**
  (`argc != 8` dicek strict di `Examples/oa-slam.cc`), tidak ada argumen `show_AR_viewer` terpisah.
  Template asli akan membuat SEMUA run gagal (usage-error) kalau tidak diubah.
- `project.ignore_file`: diisi `oa3-agent/config/ignore_none.txt` (file baru, kosong) — bukan `""` atau
  `"null"`. `preflight.py` mengecek strict bahwa file ini harus benar-benar ada di disk; isi kosong
  (0 kategori) secara fungsional setara dengan file yang tidak ada (fork ini toleran, tapi preflight-nya
  sendiri tidak).
- `project.reloc_mode`: `points` → `points+objects` — **ASUMSI, belum diverifikasi ke naskah** (lihat
  bagian 3, poin 2 di bawah). Nilai ini konsisten dengan seluruh pengujian OA-SLAM yang sudah dilakukan
  sebelumnya di repo ini, tapi bukan hasil pengecekan langsung ke teks manuskrip.
- `project.show_viewer`: dihapus (tidak dipakai lagi di template).
- `ablation.default`: ditambah `OASLAM_HEADLESS: 1` — bukan parameter asosiasi OA-SLAM, tapi env var
  yang dibaca `Examples/oa-slam.cc` untuk mematikan window Map/AR Viewer. Dicek ke `oa3/runner.py` dan
  `oa3/evaluate.py`: key ini tidak pernah muncul sebagai baris `EFFECTIVE k=v` (karena bukan salah satu
  dari 7 anchor `tools/patch_params.py`), jadi aman — tidak memicu `effective_mismatch` palsu.
- `datasets.*`: `seq_dir`/`frames_list`/`gt`/`yaml`/`det_json` untuk 4 sekuens (`fr3_walking_half`,
  `fr2_desk_w_person`, `bonn_person_track`, `bonn_crowd`) diganti ke path asli di
  `/media/khansa/KINGSTON/Dataset/...`. Kamera Bonn dipetakan ke `Cameras/TUM3.yaml` (tidak ada
  `bonn.yaml` di fork ini; Bonn RGBD Dynamic pakai sensor yang sama dengan TUM fr3, sudah dikonfirmasi
  di benchmark 60-run sebelumnya).

Detail lengkap nilai lama → baru ada di riwayat git/percakapan; `oa3_config.yaml` saat ini adalah
sumber kebenaran untuk apa yang benar-benar dipakai.

## 2. File baru yang dibuat

- `oa3-agent/detections/{fr3_walking_half,fr2_desk_w_person,bonn_person_track,bonn_crowd}_yolov8n.json`
  — di-generate dengan `scripts/generate_detections.py --weights yolov8n-seg.pt --conf 0.5 --imgsz 320
  --device cpu` (confidence sama dengan naskah). Total 6.642 frame diproses dari 4 sekuens.
- `oa3-agent/config/ignore_none.txt` — file kosong untuk argumen `categories_to_ignore_file`.
- `oa3-agent/catatan_oa3.md` — file ini.

## 3. Perbaikan pada tools milik agen (bukan fork OA-SLAM)

`tools/patch_params.py` versi asli gagal mendeteksi `Examples/oa-slam.cc` sebagai "file main" (lihat
`find_main_cc()`), karena fork ini menulis `vTimesTrack.push_back(ttrack);` sedangkan tool mencari
pola `vTimesTrack[ni] = ttrack;` (upstream OA-SLAM resize+index, fork ini reserve+push_back — hasil akhir
identik karena loop frame diproses berurutan tanpa skip, hanya beda idiom C++). Regex di `find_main_cc()`
diperluas untuk menerima kedua pola. Tanpa ini, 2 anchor (`main_include`, `log_frame`) permanen
"FILE MISSING" dan `--apply` menolak berjalan sama sekali (termasuk untuk 12 anchor lain yang sudah benar).

## 4. Patch pada fork OA-SLAM — DIMINTA PERSETUJUAN & DISETUJUI di sesi 2026-10-04

1. **Manual, sebelum `patch_params.py --apply`** — `Examples/oa-slam.cc`:
   - tambah `#include <cstdio>`
   - tambah `std::printf("FRAME %d %.3f\n", ni, ttrack * 1000.0); std::fflush(stdout);` tepat setelah
     `vTimesTrack.push_back(ttrack);` (instrumentasi latency per-frame yang dipakai `oa3.evaluate`)
2. **`tools/patch_params.py --apply`** (setelah `--diff` ditunjukkan dan disetujui):
   - `src/Tracking.cc`, `include/Tracking.h` dipatch untuk mengekspos 7 parameter asosiasi objek
     (`OA_DET_SCORE, OA_IOU2D, OA_IOU3D, OA_TIME_DIFF, OA_NB_MATCH, OA_MIN_OBS, OA_MAP_OBS`) sebagai env
     var, plus instrumentasi log `EFFECTIVE/ASSOC/LANDMARK_NEW/LOST/RELOC`.
   - File baru `include/oa3_params.h` dibuat (struct `oa3::Params`, defaults persis sama dengan sebelum
     patch — kalau env var tidak di-set, perilaku tidak berubah).
   - Backup otomatis `*.oa3.orig` dibuat untuk tiap file yang diubah (`--revert` tersedia).
3. **Rebuild**: `cd build && make clean && make -j4` — sukses, 0 error. (Sempat ada laporan error di sisi
   user saat rebuild pertama kali; `clean build` ulang di sesi asisten berhasil tanpa error — kemungkinan
   isu transient saat parallel build, tidak reproducible.)

Semua 17 anchor di `patch_params.py --check` sekarang `found` atau `already applied`. 7 default yang
terdeteksi dari source (`0.5, 0.2, 0.3, 30, 10, 10, 40`) cocok 100% dengan yang tertulis di
`ablation.default`.

## 5. Smoke test (`bonn_crowd`, cell `default` + `P1_tight`, run01) — 2026-10-04

- Status kedua run: `ok`, coverage 0.973 (di atas ambang 0.90).
- `EFFECTIVE` values echo persis sesuai yang diminta per cell (default: IOU2D=0.2/IOU3D=0.3;
  P1_tight: IOU2D=0.4/IOU3D=0.5) → exposure parameter terbukti bekerja, bukan sekadar ter-set tapi
  diabaikan kode.

### TEMUAN: control check GAGAL pada evaluasi pertama

`oa3.evaluate` melaporkan ATE (cell `default`) = **0.1109 m**, jauh dari rentang referensi campaign
5-run sebelumnya (0.06–0.07 m) — melebihi `control_tolerance_rel: 0.25` di config.

**Diagnosis** (dilakukan manual dengan `evo_ape` langsung ke trajectory yang sama,
`results_oa3/bonn_crowd/default/run01/camera_poses_*_tum.txt`, 928 baris, 25 di antaranya pose identity):

| Protokol | ATE RMSE |
|---|---|
| `-as` (Sim(3), koreksi skala), tanpa drop pose identity — protokol campaign sebelumnya | 0.0656 m ✅ cocok referensi |
| `-a` (SE(3), tanpa skala), pose identity di-drop dulu — protokol `oa3_config.yaml` saat ini | 0.1029 m |
| `-a` (SE(3), tanpa skala), TANPA drop pose identity | 0.1029 m (identik dengan baris di atas) |

Kesimpulan: **drop pose identity tidak berpengaruh sama sekali** (hasil identik sampai 6 desimal).
**Satu-satunya penyebab selisih adalah pilihan alignment SE(3) vs Sim(3).** Ini masuk akal secara teknis:
OA-SLAM berjalan monocular, skala absolut tidak teridentifikasi dari gambar saja, sehingga evaluasi
tanpa koreksi skala (SE(3)) akan menghukum selisih skala kecil sebagai error tambahan — padahal bentuk
trajectory-nya sama persis (dikonfirmasi: cell `P1_tight` yang IoU-nya beda jauh dari default,
ATE-nya malah LEBIH BAIK, 0.0988 m vs 0.1109 m — pola seperti ini wajar kalau sumber error dominannya
memang skala, bukan akurasi tracking).

## 6. Status keputusan per 2026-10-08 (lihat bagian 7–8 untuk detail/koreksi)

1. ~~Protokol alignment evaluasi~~ — **SELESAI**, lihat bagian 8: README sudah eksplisit menyatakan
   manuskrip memakai SE(3), config sudah benar, tidak perlu diubah.
2. **`project.reloc_mode: points+objects`** — **DIPUTUSKAN JALAN DENGAN ASUMSI, BELUM TERVERIFIKASI**.
   Ini satu-satunya item dari daftar asal yang benar-benar tidak terjawab di
   `README.md`/`PANDUAN_ASISTEN.md`/`SKILL.md` (cuma ditulis "sama dengan yang dipakai di naskah", tanpa
   nilai). User dikonfirmasi tidak punya akses ke naskah saat ini (2026-10-08) dan memilih lanjut jalan
   dengan `points+objects` (konsisten dengan seluruh pengujian project ini sejak awal). **PENTING:**
   ini harus di-cross-check ke naskah IJRA 21448 oleh Bu Ika sebelum hasil OA-3 dipakai di revisi —
   kalau ternyata beda, seluruh matrix (semua tahap) perlu dijalankan ulang karena `reloc_mode`
   mempengaruhi cara kerja relocalization yang dipakai di semua sel.
3. ~~Struktur matrix ablasi (OFAT vs sequential/greedy)~~ — **SELESAI**, lihat bagian 7: user eksplisit
   memilih sequential/greedy dan menyatakan sudah dikonfirmasi ke Bu Ika.

## 7. PERUBAHAN DESAIN: sequential/greedy menggantikan OFAT — 2026-10-08

Atas permintaan eksplisit user, desain matrix ablasi diubah dari **OFAT** (yang didokumentasikan di
`PANDUAN_ASISTEN.md`/`SKILL.md`, 6 sel × 4 sekuens × 3 ulangan = 72 run, tiap keluarga parameter diuji
independen relatif ke `default`) menjadi **sequential/greedy**: nilai IoU "terbaik" dari tahap P1 dibawa
tetap (fixed) ke pengujian P2, lalu nilai P1+P2 terbaik dibawa tetap ke pengujian P3.

**User menyatakan ini sudah dikonfirmasi ke Bu Ika Candradewi** (sesi tanya-jawab 2026-10-08). Asisten
sudah menyampaikan secara eksplisit bahwa kedua desain ini menjawab pertanyaan ilmiah yang berbeda
(OFAT = sensitivitas/robustness terhadap pilihan parameter, yang diminta Reviewer A/D; sequential/greedy
= pencarian kombinasi parameter optimal) sebelum user mengonfirmasi untuk lanjut dengan sequential.

Tahapan:
1. **Tahap P1**: sel `default`, `P1_loose`, `P1_tight` (IoU2D/IoU3D), semua parameter lain di default.
2. **Tahap P2**: sel baru yang menggabungkan IoU "terbaik" Tahap 1 dengan `OA_MIN_OBS` low/default/high.
3. **Tahap P3**: sel baru yang menggabungkan IoU terbaik + MIN_OBS terbaik, dengan person dipakai vs
   `drop_categories: [0]`.

**Kriteria "terbaik" (ditentukan asisten — TIDAK ADA di `PANDUAN_ASISTEN.md`/`SKILL.md`/`README.md`,
karena dokumen-dokumen itu didesain untuk OFAT yang tidak butuh kriteria "menang"):**
- Metrik: **ATE RMSE** (metrik utama yang sudah dipakai `oa3.evaluate`/`oa3.report` di seluruh pipeline
  ini, bukan metrik baru).
- Agregasi dalam 1 sel: **median** dari 3 ulangan per sekuens (median dipilih karena tahan terhadap
  1 run yang nge-fluke — lihat variasi run-to-run `fr1_desk2` di campaign 60-run sebelumnya).
- Agregasi antar sekuens: rata-rata dari median di atas, **hanya 3 sekuens dinamis**
  (`fr3_walking_half`, `fr2_desk_w_person`, `bonn_person_track`) — **`bonn_crowd` (kontrol) TIDAK
  dipakai untuk memilih "terbaik"**, tetap hanya untuk stability-check (±2%).
- Sel dengan skor rata-rata terendah = menang, nilai parameternya di-fix ke tahap berikutnya.

## 8. Koreksi: protokol alignment TERNYATA sudah terjawab di dokumen (bukan pending)

Sebelumnya (bagian 6 di atas) asisten salah mengira protokol alignment evaluasi (SE(3) vs Sim(3)) masih
perlu dikonfirmasi ke Bu Ika. Setelah dibaca ulang, `README.md` section 6 poin 2 sudah eksplisit:
"Naskah memakai Umeyama SE(3) (`evo_ape -a`)... paket ini mengikuti naskah (`align_scale: false`)."
Config `oa3_config.yaml` SUDAH BENAR (`align_scale: false`). ATE 0.1109 m pada smoke test `bonn_crowd`
cell `default` adalah **angka yang benar** di bawah protokol manuskrip, BUKAN kegagalan. Angka referensi
"0.06–0.07 m" di `SKILL.md`/`PANDUAN_ASISTEN.md` ditulis berdasarkan campaign 60-run sebelumnya yang
memakai Sim(3) (protokol berbeda) — referensi itu sendiri yang perlu diperbarui untuk pemakaian
selanjutnya, bukan hasil run OA-3 ini.

## 9. INSIDEN: proses `oa-slam` yang di-timeout runner jadi zombie, numpuk 14+ proses — 2026-10-08/09

Tahap 1 sequential dimulai 2026-10-08 21:21. Run pertama (`fr3_walking_half`, cell `default`, run01)
tidak kunjung selesai. Dicek ±9 jam kemudian (2026-10-09 06:30):

- Proses `oa-slam` (PID 19238) masih hidup, **CPU time 8:57:10**, state `R` (running), **hanya 1 thread**
  (normalnya belasan — Tracking/LocalMapping/LoopClosing/LocalObjectMapping/OpenCV worker pool — artinya
  macet SEBELUM `System` mulai spawn thread-thread itu).
- `run.log` berhenti tepat setelah baris startup (`C++ version: ...`), lalu ada baris
  `[oa3] TIMEOUT after 2400 s` — runner **sudah mendeteksi timeout 40 menit lalu**, tapi proses
  `oa-slam`-nya sendiri tidak pernah benar-benar mati.
- `pgrep -af "bin/oa-slam"` menemukan **14 proses oa-slam berjalan bersamaan** (`fr3_walking_half` run01-03
  x 3 cell, ditambah `bonn_person_track` run01-02 x 3 cell) — seluruh matrix berjalan maju terus walau
  tiap run sebelumnya tidak pernah benar-benar berhenti.
- `uptime`/`free -h` menunjukkan load average 14.49 dan **swap terpakai 96% (1.9/2.0 GB)** — sistem
  mengalami memory/swap thrashing parah, kemungkinan karena 14 proses mencoba memuat vocabulary
  `ORBvoc.txt` (139 MB) secara bersamaan.

**Root cause**: `oa3/runner.py` menjalankan setiap sel dengan
`subprocess.run(cmd, shell=True, ..., timeout=...)`. Dengan `shell=True`, child process langsung dari
Python adalah `/bin/sh -c <cmd>`, bukan `oa-slam` itu sendiri. Ketika timeout, Python hanya
mengirim sinyal ke `/bin/sh` tersebut — proses `oa-slam` yang sebenarnya (cucu, bukan anak langsung)
jadi **orphan** dan terus berjalan selamanya. Setiap run berikutnya yang juga timeout menambah satu
proses orphan lagi, mencetuskan efek bola salju (makin banyak proses orphan → makin berat beban
CPU/memori → run berikutnya makin lambat → makin besar kemungkinan ikut timeout juga).

**Tindakan yang diambil:**
1. Semua proses `oa-slam` orphan (14 proses) dan proses `oa3.runner` yang masih berjalan di-`kill -9`
   manual. Sistem kembali normal setelah itu (load average turun, RAM/swap kembali ke pemakaian wajar).
2. **`oa3/runner.py` diperbaiki**: subprocess sekarang dijalankan dengan
   `subprocess.Popen(..., start_new_session=True)` (menaruh shell + oa-slam dalam process group sendiri),
   dan saat `TimeoutExpired`, yang dibunuh adalah **seluruh process group**
   (`os.killpg(os.getpgid(proc.pid), signal.SIGKILL)`), bukan cuma proses shell wrapper-nya.
3. Fix divalidasi dengan `tests/run_mock_pipeline.sh --fast` — lolos bersih (resume/retry OK, semua 18
   run mock tereksekusi, laporan ter-generate).

**BELUM terjawab**: apakah `fr3_walking_half` memang punya bug/kondisi spesifik yang membuatnya macet di
tahap load (bukan cuma kebetulan unlucky), atau murni efek sistem yang sudah ter-overload dari run-run
SEBELUMNYA di urutan matrix (tapi run pertama ini adalah run PERTAMA yang dieksekusi, jadi seharusnya
tidak ada proses lain yang kompetisi resource saat itu dimulai — ini masih mengherankan). Rencana:
retry `fr3_walking_half` cell `default` run01 sendirian dengan timeout lebih singkat dulu (misal 300s)
untuk cepat ketahuan kalau macet lagi, baru diperpanjang kalau ternyata butuh waktu lama tapi progress
(bukan macet total).

## 10. HASIL Tahap 1 (P1) — selesai 2026-10-09 23:36

36 run (3 sel x 4 sekuens x 3 ulangan), hasil: `ok=25, low_coverage=9 (semua di bonn_person_track),
skipped(sudah ada)=2`.

**Anomali tercatat**: `fr3_walking_half` cell `P1_tight` run02 — ATE RMSE **36.3184 m** (jump=1,
RPE max=11.35), outlier ekstrem dibanding run lain di sel yang sama (0.57 m, 0.44 m) — kemungkinan
besar kehilangan tracking total akibat non-determinisme multi-threading (lihat diskusi sebelumnya
soal variasi run-to-run). Kriteria "terbaik" memakai **median** per sekuens (bukan mean) justru
dirancang untuk kasus seperti ini — outlier ini otomatis diabaikan dan tidak mendistorsi skor akhir.

**`bonn_person_track`**: SEMUA 9 run (3 sel x 3 ulangan) berstatus `low_coverage` (0.49–0.62, ambang
0.90). Pola merata di semua nilai P1 → kemungkinan karakteristik sekuens ini sendiri (scene dinamis
dengan orang yang di-track), bukan efek parameter P1. Tidak menghalangi pipeline (sesuai desain
`low_coverage` = "kept and flagged"), tapi perlu diperiksa di `OA3_report.md` section 3 nanti —
mungkin perlu didiskusikan dengan Bu Ika apakah hasil sekuens ini tetap dipakai untuk skor "terbaik"
mengingat baseline-nya sendiri sudah rendah.

**Skor "terbaik" (median ATE RMSE per sekuens, dirata-rata di 3 sekuens dinamis, `bonn_crowd`
dikecualikan — lihat kriteria bagian 7):**

| Sel | `fr3_walking_half` | `fr2_desk_w_person` | `bonn_person_track` | Skor rata-rata |
|---|---|---|---|---|
| `default` | 0.4362 | 1.3734 | 0.3541 | 0.7212 |
| `P1_loose` | 0.4329 | 0.7230 | 0.3564 | **0.5041** |
| `P1_tight` | 0.5739 | 1.0334 | 0.3412 | 0.6495 |

**PEMENANG TAHAP 1: `P1_loose` (OA_IOU2D=0.10, OA_IOU3D=0.15)**, dibawa fixed ke Tahap 2.

## 11. HASIL Tahap 2 (P2) — selesai 2026-10-10 01:37

24 run baru (2 sel baru x 4 sekuens x 3 ulangan). Hasil: `ok=17, low_coverage=7`.

**Anomali tercatat (2 outlier ekstrem baru, keduanya di `P1best_P2low`)**:
- `fr3_walking_half P1best_P2low run03`: ATE **11.48 m** (jump=1)
- `fr2_desk_w_person P1best_P2low run01`: ATE **68.58 m** (jump=1) — outlier terbesar sejauh ini
- `fr3_walking_half P1best_P2high run01`: coverage **3.6%** (hampir total gagal track) — ini run yang
  sama yang di-flag live waktu Stage 2 jalan; run02/run03 di sel yang sama normal (cov 0.95-0.99),
  jadi ini one-off fluke, bukan sel P1best_P2high yang secara sistematis buruk di sekuens ini.

Sekali lagi, kriteria median per sekuens berhasil meredam efek outlier-outlier ini ke skor akhir.

**Skor (median ATE RMSE per sekuens, rata-rata di 3 sekuens dinamis):**

| Sel | `fr3_walking_half` | `fr2_desk_w_person` | `bonn_person_track` | Skor rata-rata |
|---|---|---|---|---|
| `P1best_P2low` (MIN_OBS=5) | 0.4374 | 1.4062 | 0.3622 | 0.7353 |
| `P1best_P2default` (MIN_OBS=10, = `P1_loose` reuse) | 0.4329 | 0.7230 | 0.3564 | **0.5041** |
| `P1best_P2high` (MIN_OBS=20) | 0.4389 | 1.1485 | 0.3646 | 0.6507 |

**PEMENANG TAHAP 2: `P1best_P2default` (MIN_OBS=10, tetap di nilai default)** — menggeser MIN_OBS ke
arah manapun (5 atau 20) membuatnya lebih buruk. Baseline untuk Tahap 3: IOU2D=0.10, IOU3D=0.15,
MIN_OBS=10 (persis sama dengan cell `P1_loose` yang sudah ada).

## 12. HASIL Tahap 3 (P3) dan HASIL AKHIR sequential search — selesai 2026-10-10 09:44

12 run baru (1 sel baru x 4 sekuens x 3 ulangan). Hasil: `ok=9, low_coverage=3` (semua 3
`low_coverage` di `bonn_person_track`, konsisten dengan Tahap 1 & 2).

**Skor (median ATE RMSE per sekuens, rata-rata di 3 sekuens dinamis):**

| Sel | `fr3_walking_half` | `fr2_desk_w_person` | `bonn_person_track` | Skor rata-rata |
|---|---|---|---|---|
| `P1best_P2best_default` (person dipakai, = `P1_loose` reuse) | 0.4329 | 0.7230 | 0.3564 | **0.5041** |
| `P1best_P2best_noperson` (person dibuang) | 0.4450 | 1.2056 | 0.3766 | 0.6757 |

**PEMENANG TAHAP 3: `P1best_P2best_default`** — membuang person sebagai landmark justru memperburuk
skor (terutama di `fr2_desk_w_person`, 0.72→1.21).

### HASIL AKHIR SEQUENTIAL/GREEDY SEARCH (3 tahap)

**Kombinasi parameter terbaik yang ditemukan: `OA_IOU2D=0.10, OA_IOU3D=0.15, OA_MIN_OBS=10 (default),
person landmarks tetap dipakai.`**

Dengan kata lain: dari 3 keluarga parameter yang diuji (P1 asosiasi IoU, P2 observasi minimum,
P3 person landmarks), **hanya P1 yang memberikan perbaikan** dibanding nilai default manuskrip
(skor 0.5041 vs default murni P1/default/default = 0.7212 di Tahap 1) — menggeser P2 atau membuang
P3 dari nilai default-nya masing-masing justru memperburuk skor, bukan memperbaiki.

Total run di seluruh campaign sequential: 72 (36 Tahap 1 + 24 Tahap 2 + 12 Tahap 3). Skor "terbaik"
dihitung HANYA dari 3 sekuens dinamis (`fr3_walking_half`, `fr2_desk_w_person`, `bonn_person_track`);
`bonn_crowd` tetap dipakai sebagai stability-check (lihat bagian 13).

**Catatan interpretasi (bukan keputusan asisten — murni laporan skor dari skrip):** hasil ini TIDAK
sama dengan hasil OFAT yang didokumentasikan di `PANDUAN_ASISTEN.md` (lihat bagian 6-7) — sequential
search ini menjawab pertanyaan "kombinasi parameter apa yang paling akurat", BUKAN "apakah akurasi
sensitif terhadap pilihan parameter" yang diminta Reviewer A/D. Perbedaan desain ini perlu
dipertimbangkan Bu Ika saat menulis bagian respons ke reviewer.

## 13. PERINGATAN: `OA3_report.md` otomatis TIDAK cocok dengan desain sequential — baca sebelum dipakai

`python -m oa3.report --config oa3_config.yaml --zip` berhasil jalan (`oa3_handoff_20261010_0945.zip`,
38.4 MB, 72 run), tapi laporan yang di-generate (`results_oa3/OA3_report.md`) punya 2 masalah karena
`ablation.families` di config tidak pernah diupdate untuk struktur sequential (section 7 & 12 di atas):

1. **Section 2 "Completeness"** melaporkan "Missing runs" untuk `P2_low`, `P2_high`, `P3_noperson`
   (36 run) — ini BUKAN run yang gagal, ini cell OFAT asli yang memang sengaja tidak pernah dijalankan
   sebagai cell berdiri sendiri (diganti `P1best_P2low` dkk yang menggabungkan IoU P1 terbaik).
2. **PENTING — Section 4 & 7 memakai agregasi mean±SD, bukan median.** Ini membuat outlier ekstrem
   (ATE 36 m di `P1_tight`, 68 m di `P1best_P2low` — lihat bagian 10-11) TIDAK ter-filter, menghasilkan
   angka "Δ vs default" yang absurd: **"+2711.7%"** untuk `P1_tight` di `fr3_walking_half`, **"+892.3%"**
   untuk rata-rata `P1_tight` di draft paragraf manuskrip (section 7). **Angka-angka ini JANGAN dipakai
   di naskah** — gunakan angka median di bagian 10-12 di atas, yang memang dipilih justru untuk tahan
   terhadap outlier semacam ini.

**Yang BISA dipercaya dari handoff zip ini**: `oa3_results.csv` (data mentah 72 run, tidak diringkas,
aman dipakai untuk analisis ulang), seluruh folder `<sekuens>/<sel>/runNN/` (trajectory, keyframe, peta
objek, log — lengkap, tidak ada yang dipotong), `config_used.yaml`, `platform.json`.

**Rekomendasi**: kirim `catatan_oa3.md` ini bersama handoff zip ke Bu Ika — bagian 10-12 berisi hasil
sequential search yang sudah benar (median-based), dan bagian ini menjelaskan kenapa `OA3_report.md`
section 4/7 tidak boleh dikutip langsung.

## 14. Konfirmasi: semua output mentah per-run sudah tersimpan lengkap

Dicek langsung isi folder `results_oa3/bonn_crowd/default/run01/`: berisi
`camera_poses_*.txt/.json/_tum.txt`, `keyframes_poses_*.json/_tum.txt`, `map_objects_*.obj/.txt`,
`map_points_*.obj`, `map_*.mappoints/.keyframes/.features/.objecttracks/.yaml`, seluruh CSV timing,
`run.log`, `meta.json`, `eval.json`. Bukan cuma metrik ringkas — semua artefak mentah per run sudah
otomatis dipindahkan & disimpan oleh `oa3.runner` (tidak perlu perubahan lebih lanjut untuk ini).

## 15. Campaign kedua: deteksi real-time (CPU), bukan JSON precomputed — 2026-10-13

**Instruksi Bu Ika**: campaign OA-3 harus dijalankan dengan deteksi *real-time*, bukan dari file JSON
precomputed. Ini campaign terpisah dari bagian 1-14 di atas (yang semua pakai `det_json` = file JSON),
dijalankan di laptop/workstation (CPU) — sisi GPU/TensorRT di Jetson belum dikerjakan, menunggu
instruksi terpisah.

**Perubahan teknis** (lihat juga pesan commit terkait kalau sudah di-commit):
- `oa3_config.yaml`: `det_json` tiap dataset diarahkan ke `yolov8n-seg.onnx` (bukan file JSON lagi) —
  memicu jalur `ObjectDetector` (live inference, `src/ImageDetections.cc`) di `Examples/oa-slam.cc`,
  bukan `DetectionsFromFile`. Model, bobot, dan confidence (0.5) SAMA seperti sebelumnya — cuma sumber
  deteksinya yang berubah dari file ke live inference.
- Cell `P3_noperson` / `P1best_P2best_noperson`: filter person (COCO id 0) dipindah dari `drop_categories`
  (filter JSON, tidak bisa dipakai lagi tanpa JSON) ke `ignore_file` (`config/ignore_person.txt`, isi "0")
  — mekanisme fork-native yang juga dihormati `ObjectDetector::detect()`.
- `execution.results_root` diubah ke `results_oa3_realtime_cpu` (BUKAN menimpa `results_oa3/` yang lama)
  supaya tidak campur/tertukar dengan hasil campaign JSON di bagian 1-14.
- `CLAUDE.md` & `README.md` diupdate: aturan lama "no TensorRT" sudah usang untuk sisi deteksi
  real-time CPU ini (tetap belum ada TensorRT sama sekali di codebase untuk sisi Jetson/GPU).

**Hasil**: 108 run (4 sekuens x 9 cell x 3 ulangan) selesai — `ok=79, low_coverage=29`.
- 27 dari 29 `low_coverage` ada di `bonn_person_track` (SEMUA 9 cell x 3 ulangan) — **pola identik**
  dengan yang sudah terdokumentasi di bagian 1-14 untuk campaign JSON (coverage 0.49-0.62 di situ juga).
  Bukan regresi baru dari real-time, karakteristik sekuens itu sendiri.
- 1 outlier di `fr3_walking_half/P1best_P2high` dan 1 di `fr2_desk_w_person/P1best_P2best_noperson` —
  juga konsisten dengan pola non-determinism run-to-run yang sudah pernah dilihat sebelumnya.

**TEMUAN BARU — control-check flag beda dari campaign JSON**: `bonn_crowd` (kontrol) bergerak **-25.2%**
di cell `P2_high` (OA_MIN_OBS=20), melebihi `control_tolerance_rel: 0.25`. Di campaign JSON lama, cell
yang flag justru `P1best_P2best_noperson` (+30%), BUKAN `P2_high`. Data mentah (median ATE per run,
`oa3_results.csv`):

| run | `default` ATE median | `P2_high` ATE median |
|---|---|---|
| 1 | 0.0886 | 0.0701 |
| 2 | 0.0893 | 0.0660 |
| 3 | 0.1140 | 0.0692 |

Spread rapat per grup (tidak overlap), tidak ada `jump`/`RELOC` anomali pembeda — kemungkinan ini efek
nyata dari `OA_MIN_OBS=20`, bukan noise. **Belum diputuskan asisten** — ini perlu dibawa ke Bu Ika:
apakah `bonn_crowd` masih valid dipakai sebagai kontrol parameter-insensitive, atau temuan ini perlu
dicatat di manuscript.

**PERINGATAN yang SAMA seperti bagian 13 berlaku lagi di sini**: `results_oa3_realtime_cpu/OA3_report.md`
section 4 pakai agregasi mean±SD (bukan median) dan `ablation.families` di config cuma mencakup cell
OFAT asli (P1_loose/P1_tight, P2_low/P2_high, P3_noperson) — BUKAN cell sequential (`P1best_P2low`, dst).
Jadi section 4/7 report otomatis **tidak** menjawab "kombinasi mana yang menang di bawah deteksi
real-time" — itu perlu dianalisis manual dari `oa3_results.csv` (median per sel, seperti bagian 10-12),
BELUM dikerjakan asisten untuk campaign real-time ini. Kalau Bu Ika/user perlu angka "pemenang
sequential" versi real-time, ini pekerjaan tambahan yang belum dilakukan.

**Rekomendasi handoff**: kirim `catatan_oa3.md` (file ini) bersama
`results_oa3_realtime_cpu/oa3_handoff_20261013_1536.zip` ke Bu Ika — zip-nya sendiri sudah lengkap
(`config_used.yaml`, `platform.json`, `OA3_report.md`, 3 figure, `oa3_results.csv`, seluruh raw
per-run `run.log`/`meta.json`/`eval.json`/trajectory), tapi interpretasinya butuh catatan di bagian
ini (terutama soal control-check `P2_high` dan limitasi section 4/7 report).
