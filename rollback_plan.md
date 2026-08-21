# Rollback Plan — Migrasi Tahap 1 AquaNotes

## Batas aman

- Origin lama: server Tailscale lama, aplikasi pada port 8000 dan sqlite-web pada port 8001.
- Origin baru: `192.168.10.100:8000` untuk API dan `192.168.10.100:8001` untuk sqlite-web.
- Hostname publik tidak berubah.
- Database lama tidak boleh dihapus atau dimodifikasi secara manual selama masa rollback.
- Backup baseline dan final harus memiliki `PRAGMA integrity_check = ok` dan SHA-256 yang tercatat.

## State persiapan 10 Agustus 2026

- Backup baseline: `/srv/aquanotes/backup/aquanotes-baseline-20260810T014912Z.db`
- SHA-256 baseline: `0504557e5f167d52389581b6ac7bf1203aa20fd76bae13cf02aa539acfbac56f`
- Baseline: 994.729 `sensor_data` dan 792.835 `notifications`.
- `sqlite-web` baru aktif read-only pada port 8001 dan memerlukan password.
- API baru telah lulus dry-run tetapi sengaja dihentikan sampai final sync/cutover.
- Server lama tetap menjadi origin produksi dan tetap menerima write.

## State setelah cutover 10 Agustus 2026

- Cutover Cloudflare terdeteksi sekitar 10:17–10:18 WITA/SGT.
- Backup final: `/srv/aquanotes/backup/aquanotes-final-20260810T021313Z.db`
- SHA-256 final: `9c92845dc0a7bfa30a66036d6ad4de7f034951b3c387ef8a0aafb7cd41d9684b`
- Data final sebelum start: 994.819 `sensor_data` dan 792.962 `notifications`.
- API publik `/docs`, `/openapi.json`, dan bearer token lama telah lulus HTTP 200.
- Data IoT nyata pertama teramati pada database baru dengan timestamp `2026-08-10 10:18:14` dan terus bertambah.
- `sqlite-web` publik mewajibkan login dan database view telah tervalidasi.
- `fastapi.service` dan `sqliteweb.service` pada server lama harus tetap inactive.
- Karena origin baru sudah menerima write, gunakan prosedur **rollback setelah origin baru menerima write** jika rollback diperlukan.

## Kondisi rollback

Rollback dilakukan jika salah satu terjadi setelah perubahan Cloudflare:

- `/docs` atau `/openapi.json` gagal/timeout.
- `POST /sensor/` gagal selama satu interval pengiriman perangkat.
- Bearer token Android lama tidak valid.
- Data baru tidak persisten atau row count turun.
- Error 5xx berulang, database terkunci, atau notifikasi FCM ganda secara luas.

## Rollback sebelum origin baru menerima write

1. Arahkan hostname API Cloudflare kembali ke origin lama port 8000.
2. Arahkan hostname sqlite-web kembali ke origin lama port 8001.
3. Pastikan Uvicorn dan sqlite-web lama masih aktif.
4. Validasi `/docs`, token Android lama, dan satu payload sensor canary.
5. Stop container baru tanpa menghapus volume:

```bash
cd /srv/aquanotes
docker compose -f compose.yml -f compose.cutover.yml stop
```

## Rollback setelah origin baru menerima write

Jangan langsung mengembalikan Cloudflare ke server lama karena write baru di database baru akan hilang.

1. Catat waktu UTC saat rollback diputuskan.
2. Hentikan perubahan Android dan pastikan retry IoT aktif.
3. Stop API baru secara graceful, tetapi jangan hapus container/volume.
4. Buat backup database baru dengan SQLite backup API ke file baru.
5. Bandingkan `max(id)` dan timestamp terhadap backup final lama.
6. Ekspor/merge seluruh delta baru ke salinan database lama.
7. Jalankan integrity check, row-count, orphan check, dan canary test.
8. Start service lama dengan database hasil rekonsiliasi.
9. Baru arahkan Cloudflare kembali ke origin lama.

Jika merge delta belum teruji, pilihan aman adalah mempertahankan origin baru sambil memperbaiki masalah, bukan melakukan rollback database secara buta.

## Perintah pemeriksaan cepat

Di origin baru:

```bash
cd /srv/aquanotes
docker compose -f compose.yml -f compose.cutover.yml ps
docker compose -f compose.yml -f compose.cutover.yml logs --tail=200 api
curl -fsS http://192.168.10.100:8000/openapi.json >/dev/null
```

Di origin lama:

```bash
pgrep -af 'uvicorn app.main:app'
pgrep -af 'sqlite_web'
curl -fsS http://127.0.0.1:8000/openapi.json >/dev/null
```

## Data yang tidak boleh dihapus

- `/home/frey/FastAPI_SQLite/iot_server_4/aquanotes.db`
- `/home/frey/aquanotes-migration/`
- `/srv/aquanotes/data/aquanotes.db`
- `/srv/aquanotes/backup/`
- `.migration_staging/` di laptop sampai observasi selesai

## Rollback khusus perbaikan spam notifikasi (2026-08-10)

- Backup SQLite sebelum deployment: `/srv/aquanotes/backup/notification-fix-20260810T155130Z/aquanotes.db`
- Backup source lama: `/srv/aquanotes/backup/notification-fix-20260810T155130Z/source/`
- Image lama: `aquanotes-api:pre-notification-fix-20260810t155130z`

Rollback source saja (tabel internal baru aman dibiarkan dan diabaikan oleh kode lama):

```bash
cd /srv/aquanotes
cp -a backup/notification-fix-20260810T155130Z/source/background_tasks.py app/app/background_tasks.py
cp -a backup/notification-fix-20260810T155130Z/source/models.py app/app/models.py
docker compose -f compose.yml -f compose.cutover.yml build api
docker compose -f compose.yml -f compose.cutover.yml up -d --no-deps api
```

Jangan menimpa database aktif dengan backup kecuali integrity check gagal. Jika database harus dipulihkan, hentikan API, buat backup SQLite dari database aktif terlebih dahulu, lalu rekonsiliasi semua write setelah `2026-08-10T15:51:30Z`.

## Rollback khusus rotasi ADMIN_API_KEY (2026-08-11)

- Backup SQLite: `/srv/aquanotes/backup/admin-security-20260810T164820Z/aquanotes.db`
- Backup source admin lama: `/srv/aquanotes/backup/admin-security-20260810T164820Z/admin.py`
- Backup environment lama: `/srv/aquanotes/backup/admin-security-20260810T164820Z/app.env`
- Image lama: `aquanotes-api:pre-admin-security-20260810t164820z`

Rollback source dan environment hanya jika tool provisioning belum dapat memakai key baru:

```bash
cd /srv/aquanotes
cp -a backup/admin-security-20260810T164820Z/admin.py app/app/routers/admin.py
cp -a backup/admin-security-20260810T164820Z/app.env secrets/app.env
chmod 600 secrets/app.env
docker compose -f compose.yml -f compose.cutover.yml build api
docker compose -f compose.yml -f compose.cutover.yml up -d --no-deps api
```

Rollback ini mengaktifkan kembali key yang pernah terekspos di Git publik dan hanya boleh dipakai sebagai tindakan darurat sementara.

## Selesai rollback bila

- Semua hostname publik kembali memberi respons normal.
- Setiap UID aktif kembali mengirim data.
- Token Android lama berhasil.
- Data sebelum dan selama window migrasi telah direkonsiliasi.
- Bukti hash, count, timestamp, dan log disimpan.

## Rollback khusus assignment history (22 Agustus 2026)

Backup rehearsal/baseline pertama:

- `/srv/aquanotes/backup/assignment-stage1-20260821T174420Z/aquanotes.before.db`
- SHA-256: `1dc164c4b3d7a8dc0a518e22ecda42e83db34920cdf7f5c5f335987521b7026d`

Backup final production dan image rollback:

- `/srv/aquanotes/backup/assignment-cutover-20260821T175349Z/aquanotes.before.db`
- SHA-256: `3a5ab595dccc7a039209b98d1854a9846c6c361f0e02b69335e25a3911943ac3`
- Source lama: `/srv/aquanotes/backup/assignment-cutover-20260821T175349Z/source`
- Image lama: `sha256:30963964ee23e23d0961ed704793a39e062bd79b3061fec6f31f7eec977db472`
- Tag image lama: `aquanotes-api:pre-assignment-20260821T175349Z`
- Commit baru: `8241caf8ec35ee143f76a1c451e9ae0a7b715ff0`
- Cutoff sensor ID: `1128233`

Rollback aplikasi saja aman: kode versi sebelumnya mengabaikan tabel
`device_assignments` dan kolom nullable `sensor_data.assignment_id`. Utamakan
rollback image/source tanpa mengganti database agar write IoT terbaru tidak hilang.

Jika schema harus dikembalikan, hentikan API dan simpan backup database aktif
terlebih dahulu. Jangan restore backup lama secara langsung setelah production
menerima write. Rekonsiliasi semua row sensor, perubahan device, tambak, kolam,
token, dan notifikasi setelah timestamp backup, baru lakukan penggantian atomik.

Kriteria rollback:

- `POST /sensor/` gagal atau tidak menambah tepat satu row.
- Token mobile lama, `/monitoring`, atau endpoint utama menghasilkan 5xx.
- Row count berkurang, integrity/FK check gagal, atau terjadi mismatch assignment.
- `database is locked` berulang melewati timeout 30 detik.
