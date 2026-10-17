# Riwayat parameter dan pengaturan alarm web

## Perubahan

- Endpoint baru `GET /monitoring/devices/{device_id}/history?parameter=ph&limit=24&before_id=...`.
- Parameter whitelist: suhu, ph, do, tds, ammonia, salinitas. Limit 1–100; cursor milik perangkat/scope yang sama.
- Pencarian dimulai dari nilai terakhir yang tidak null, lalu mempertahankan seluruh celah null dalam jendela histori. Pagination memakai timestamp dan ID agar pembacaan bertimestamp sama tidak hilang.
- Pemilik perangkat hanya mendapat data assignment milik akunnya. Admin dapat membaca histori perangkat; hak edit threshold tidak diperluas.
- Endpoint lama, payload IoT, kontrak mobile, schema database, serta data tersimpan tidak diubah.
- Pengaturan alarm web memakai GET/PUT threshold existing: null mematikan batas, sedangkan 0 sah. Backend melewati alarm jika nilai sensor atau threshold null.

## Deployment production

API image: `aquanotes-api:20261017-history`, dibuat dari image API yang sedang berjalan dan hanya menyalin schemas.py serta routers/monitoring.py. Source awal sudah dicocokkan dengan production (normalisasi CRLF).

Release API: `/home/dockeradmin/releases/aquanotes-history-20261017`. Compose dasar: `/home/dockeradmin/releases/aquanotes-3793abc/deployment/stage2/compose.yml`. Override image: `.migration_staging/history-release/compose.patch.yml` di release API.

Preflight terpisah dengan MQTT/background task nonaktif, unit tests, health/OpenAPI dan query baca PostgreSQL lulus sebelum API lama diganti. Web image: `aquanotes-web:20261017-history-alarm`; release `/home/dockeradmin/releases/aquanotes-web-20261017-history-alarm`.

## Verifikasi

- 10 unit tests dan 6 subtests terkait histori, assignment, route kompatibilitas, dan state alarm lulus.
- Tes browser sintetis: nilai terkini null tetapi histori tersedia, null gaps, pagination, nilai 0, tidak ada histori, save/reload threshold, validasi batas kosong, off → null.
- Halaman admin/user diuji 320–1440px; animasi dan reduced-motion tetap lulus.
- Query baca production device 29: histori pH/TDS/salinitas tanggal 5 September dapat diambil, ammonia belum memiliki histori.
- Tidak mengubah threshold akun production untuk pengujian. Device 29 tetap mengirim telemetry setelah cutover API.

## Rollback

Tidak perlu rollback database karena tidak ada migrasi schema atau perubahan data.

1. Rollback web dahulu: dari release web di atas, jalankan `WEB_IMAGE=aquanotes-web:20261017-chart-motion docker compose -p stage2 -f deployment/compose.web.yml up -d --no-deps web`.
2. Dari release API, baca `api-image-before.txt` (saat deployment: stage2-api), lalu jalankan compose dasar + override dengan `API_IMAGE=stage2-api` dan `up -d --no-deps --no-build api`.
3. Periksa health API/web serta freshness telemetry. Jangan gunakan `--remove-orphans`, jangan menghapus volume, dan jangan mengubah origin Cloudflare.

Batasan: UI hanya dapat menampilkan data yang benar-benar pernah diterima server. Nilai null tidak membuktikan sensor dicabut; bisa juga belum ada pembacaan atau gangguan sensor/kabel.
