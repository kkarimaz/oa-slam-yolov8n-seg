# Panduan Eksperimen OA-3 untuk Asisten Peneliti

Per 2026-10-01 · Ika Candradewi

OA-3 adalah analisis sensitivitas parameter asosiasi objek OA-SLAM-YOLOv8n untuk revisi IJRA 21448: 6 sel × 4 sekuens × 3 ulangan = 72 run, dijalankan dengan paket `oa3-agent`. Hasil akhirnya satu berkas `oa3_handoff_<tanggal>.zip` yang dikirim ke Bu Ika; semua angka berasal dari skrip, tidak ada yang dihitung manual.

## 1. Tujuan dan aturan main

OA-3 menjawab Reviewer A dan D: apakah selisih akurasi OA-SLAM-YOLOv8n terhadap YSLAMv8n/v11n disebabkan oleh pengaturan parameternya, bukan oleh paradigma landmark objek. Caranya: satu parameter diubah pada satu waktu (OFAT) di sekitar nilai default, tiap sel diulang 3 kali, lalu ATE/RPE dibandingkan dengan sel default.

| Keluarga | Sel | Nilai | Arti |
| --- | --- | --- | --- |
| P1 asosiasi | `P1_loose` / `default` / `P1_tight` | IoU2D/IoU3D 0.10/0.15 / 0.20/0.30 / 0.40/0.50 | gerbang IoU deteksi terhadap track dan proyeksi elipsoid |
| P2 observasi | `P2_low` / `default` / `P2_high` | OA_MIN_OBS 5 / 10 / 20 | observasi minimum sebelum elipsoid diinisialisasi |
| P3 person | `default` / `P3_noperson` | kelas person (id 0) dipakai / dibuang | deteksi person tidak pernah menjadi landmark |

Sekuens: `fr3_walking_half`, `fr2_desk_w_person`, `bonn_person_track`, `bonn_crowd` (kontrol; reprodusibel ±2 % pada kampanye 5 run). Total 6 sel × 4 sekuens × 3 ulangan = 72 run.

Aturan yang tidak boleh dilanggar:

- Jangan ubah detektor, bobot, ambang confidence 0.5, JSON deteksi, pengaturan ORB, YAML kamera, atau dataset. Hanya variabel di `oa3_config.yaml` yang berubah.
- Jangan jalankan dua run OA-SLAM bersamaan dan jangan jalankan program berat lain selama matriks berjalan (OA-SLAM memutar sekuens pada laju sensor; beban CPU mengubah hasil).
- Jangan menyunting apa pun di folder hasil (`results_oa3/`) dengan tangan; bila ada yang salah, jalankan ulang skripnya.
- Jangan menebak nilai default parameter: nilainya dibaca dari kode oleh `tools/patch_params.py --check`.
- Satu titik persetujuan wajib: **matriks penuh baru dijalankan setelah Bu Ika menyetujui hasil smoke test** (Langkah 5).
- Catat setiap keanehan (run gagal, laptop sempat tidur, pesan error) di `catatan_oa3.md`; catatan ini ikut dikirim.


