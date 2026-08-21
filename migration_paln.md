# Rencana Migrasi AquaNotes ke Server Baru

> Nama file mengikuti permintaan awal (`migration_paln.md`). Dokumen ini adalah runbook operasional. Jangan melakukan cutover sebelum seluruh gate bertanda **WAJIB** terpenuhi.

## 1. Tujuan dan prinsip migrasi

Tujuan migrasi:

- Seluruh data produksi tetap utuh dan dapat diverifikasi.
- Perangkat IoT tetap mengirim ke URL yang sama: `https://aeraseaku.inkubasistartupunhas.id/sensor/`.
- Aplikasi Android tetap memakai hostname, path API, format JSON, dan bearer token yang sama.
- URL dokumentasi tetap tersedia di `https://aeraseaku.inkubasistartupunhas.id/docs`.
- Rollback dapat dilakukan tanpa menimpa satu-satunya salinan database.

Strategi yang direkomendasikan adalah **dua tahap**:

1. **Tahap A — lift-and-shift:** pindahkan aplikasi beserta SQLite produksi ke LXC 101/Docker tanpa mengubah kontrak API atau mesin database.
2. **Tahap B — SQLite ke PostgreSQL:** setelah layanan baru stabil, ubah aplikasi agar mendukung PostgreSQL LXC 102, lakukan migrasi data terpisah, lalu cutover internal database.

Jangan menggabungkan perpindahan server, containerisasi, perubahan dependency, dan konversi PostgreSQL dalam satu cutover. Project saat ini belum siap memakai PostgreSQL tanpa perubahan kode.

## 2. Kondisi project yang telah diverifikasi

### Produksi lama

- Service aktif menjalankan `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- Working directory produksi adalah project `iot_server_4`.
- Database produksi adalah `aquanotes.db` sekitar **249 MB** menurut catatan tanggal 10 Agustus 2026.
- Database `aquanotes.db` di repository lokal hanya **100 KB** dan berisi data contoh. **Jangan gunakan file lokal sebagai sumber migrasi.**
- Belum terlihat supervisor/systemd dari catatan yang tersedia; proses Uvicorn tampak dijalankan langsung.

### Aplikasi dan kompatibilitas klien

- IoT menulis melalui `POST /sensor/` dengan JSON berisi `uid`, `suhu`, `ph`, `do`, `tds`, `ammonia`, dan `salinitas`.
- Endpoint tulis IoT tidak memakai bearer token; identitas perangkat ditentukan dari `devices.uid`.
- Android login melalui `POST /users/login` dan menerima UUID bearer token.
- Token tersimpan di tabel `auth_tokens` dengan masa berlaku default 720 jam. Tabel ini wajib dimigrasikan agar pengguna Android tidak diminta login ulang.
- FCM token tersimpan pada `users.fcm_token`; credential Firebase Admin berada di luar Git dan wajib dipindahkan sebagai secret.
- Background thread memeriksa threshold serta status perangkat setiap 60 detik. Jalankan hanya **satu worker aplikasi** sampai mekanisme background job dipisahkan, agar notifikasi tidak ganda.
- Semua router saat ini berada di root path; jangan menambahkan prefix seperti `/api` atau mengubah trailing slash.

### Database dan deployment

- `app/database.py` masih hard-coded ke `sqlite:///./aquanotes.db` dan memakai opsi khusus SQLite.
- `app/main.py` menjalankan `sqlite3.connect('aquanotes.db')` dan `PRAGMA table_info`; kode ini tidak kompatibel dengan PostgreSQL.
- Path database bersifat relatif. Working directory yang salah dapat membuat database kosong baru. Container harus memiliki working directory tetap dan volume database absolut.
- `requirements.txt` saat ini bukan lockfile aplikasi yang lengkap; dependency seperti FastAPI, Uvicorn, SQLAlchemy, Passlib/bcrypt, Firebase Admin, Pydantic/email validator, dan driver PostgreSQL tidak tercantum.
- Import aplikasi dari environment lokal saat ini gagal karena `passlib` tidak tersedia. Dependency produksi harus diambil dari virtualenv lama yang benar-benar berjalan, lalu diuji dalam image baru.
- Credential Firebase yang dibutuhkan kode bernama `aqua-notes-firebase-adminsdk-fbsvc-6de08d39b2.json`; `google-services.json` Android bukan penggantinya.
- `app/main.py` tidak memasukkan router admin. Pertahankan perilaku tersebut selama migrasi kecuali perubahan API memang direncanakan terpisah.

### Schema yang wajib dipertahankan

Tabel: `users`, `auth_tokens`, `tambak`, `devices`, `kolam`, `sensor_data`, dan `notifications`.

Relasi/kolom kritis:

- `users.id`, `users.email`, `users.password_hash`, `users.fcm_token`
- `auth_tokens.token`, `auth_tokens.user_id`, `auth_tokens.expires_at`
- `devices.id`, `devices.uid`, `devices.user_id`, threshold, `last_seen`, `status`, `connection_interval`
- `tambak.user_id`, `kolam.tambak_id`, `kolam.device_id`
- `sensor_data.id`, `sensor_data.device_id`, `sensor_data.timestamp`
- `notifications.user_id`, `notifications.device_id`, `is_read`, `fcm_sent`, `timestamp`

## 3. Aturan keamanan sebelum mulai

- [ ] **WAJIB:** hapus password plaintext dari dokumen operasional dan pindahkan ke password manager.
- [ ] **WAJIB:** rotasi seluruh password SSH yang pernah ditulis di file project/chat.
- [ ] **WAJIB:** gunakan SSH key, nonaktifkan login root/password bila akses key sudah teruji.
- [ ] **WAJIB:** jangan commit `.env`, SQLite produksi, backup, dump PostgreSQL, atau Firebase Admin service account.
- [ ] Salin Firebase Admin JSON melalui kanal aman ke secret/volume read-only.
- [ ] Batasi PostgreSQL agar hanya menerima koneksi dari LXC 101 dan jaringan administrasi yang diperlukan.
- [ ] Buat user PostgreSQL khusus aplikasi, bukan user superuser.

Contoh placeholder yang dipakai di dokumen ini:

```bash
OLD_HOST=<tailscale-ip-server-lama>
APP_HOST=<ip-lokal-lxc-101>
PG_HOST=<ip-lokal-lxc-102>
```

## 4. Gate nol kehilangan data

Tidak ada prosedur yang dapat menjamin nol kehilangan data saat write dihentikan jika firmware IoT tidak melakukan retry. Sebelum cutover:

- [ ] **WAJIB:** pastikan firmware IoT retry dengan backoff saat timeout, HTTP 502/503, atau koneksi putus.
- [ ] **WAJIB:** catat interval kirim setiap perangkat aktif dan UID-nya.
- [ ] **WAJIB:** lakukan uji terkontrol: putuskan origin selama 30–60 detik, hidupkan kembali, lalu pastikan pembacaan yang gagal dikirim ulang atau disimpan lokal.
- [ ] Jika perangkat tidak retry/spool, **jangan cutover langsung**. Tambahkan temporary ingestion relay/queue atau perbaiki firmware terlebih dahulu.
- [ ] Tentukan maintenance window saat aktivitas Android rendah.
- [ ] Bekukan perubahan akun/tambak/kolam/device dari Android selama final copy.

Target praktis Tahap A adalah downtime kurang dari beberapa menit. Cloudflare hostname tidak berubah, sehingga tidak ada propagasi DNS dan klien tidak perlu update aplikasi/firmware.

## 5. Tahap A — persiapan server baru dengan SQLite

### 5.1 Inventaris produksi lama

Jalankan read-only checks di server lama dan simpan output sebagai evidence bertanggal:

```bash
cd /home/frey/FastAPI_SQLite/iot_server_4
pwd
ps aux | grep -E "uvicorn|gunicorn|fastapi"
python --version
/home/frey/FastAPI_SQLite/venv/bin/pip freeze > ~/aquanotes-evidence/pip-freeze.txt
sha256sum aquanotes.db > ~/aquanotes-evidence/aquanotes.live.sha256
sqlite3 aquanotes.db "PRAGMA journal_mode; PRAGMA foreign_keys; PRAGMA integrity_check;"
```

Catat juga:

- [ ] Command startup aktual dan user proses.
- [ ] Port listener dan firewall.
- [ ] Semua environment variable **tanpa mencetak nilai secret**.
- [ ] Lokasi credential Firebase Admin.
- [ ] Ukuran database dan ruang disk bebas.
- [ ] Daftar UID perangkat, `last_seen`, interval, dan status sebelum migrasi.
- [ ] Row count serta nilai ID maksimum untuk setiap tabel.

Query baseline:

```sql
SELECT 'users', count(*), max(id) FROM users;
SELECT 'devices', count(*), max(id) FROM devices;
SELECT 'tambak', count(*), max(id) FROM tambak;
SELECT 'kolam', count(*), max(id) FROM kolam;
SELECT 'sensor_data', count(*), max(id), min(timestamp), max(timestamp) FROM sensor_data;
SELECT 'notifications', count(*), max(id), min(timestamp), max(timestamp) FROM notifications;
SELECT 'auth_tokens', count(*), min(expires_at), max(expires_at) FROM auth_tokens;
```

### 5.2 Buat backup berlapis

Saat aplikasi masih berjalan, buat baseline konsisten memakai SQLite backup API, bukan `cp` biasa:

```bash
mkdir -p ~/aquanotes-backup
sqlite3 aquanotes.db ".timeout 10000" ".backup '~/aquanotes-backup/aquanotes-baseline.db'"
sqlite3 ~/aquanotes-backup/aquanotes-baseline.db "PRAGMA integrity_check;"
sha256sum ~/aquanotes-backup/aquanotes-baseline.db
```

Catatan: pada beberapa shell, `~` di dalam perintah SQLite tidak diekspansi. Jika gagal, gunakan path absolut user lama.

Simpan minimal tiga salinan:

- [ ] Salinan asli tetap di server lama dan tidak disentuh.
- [ ] Salinan terenkripsi di server baru.
- [ ] Salinan terenkripsi di media/host ketiga.
- [ ] Verifikasi hash setelah setiap transfer.
- [ ] Uji restore backup ke nama file lain dan jalankan `PRAGMA integrity_check`.

### 5.3 Bangun image yang identik

- [ ] Gunakan versi source yang sama dengan `iot_server_4` produksi; jangan menganggap branch lokal otomatis sama.
- [ ] Bandingkan checksum source lama dengan checkout yang akan dibangun.
- [ ] Bentuk dependency lock dari `pip freeze` produksi, lalu hilangkan paket yang terbukti tidak relevan hanya setelah smoke test.
- [ ] Container memakai satu Uvicorn worker dan `WORKDIR` yang konsisten.
- [ ] Mount database, Firebase credential, dan config sebagai volume/secret; jangan bake ke image.
- [ ] Gunakan restart policy dan health check.
- [ ] Jangan expose port 8000 langsung ke internet; origin diakses Cloudflare Tunnel/LAN yang dibatasi.

Layout contoh:

```text
/srv/aquanotes/
├── app/                     # source/image metadata
├── data/aquanotes.db        # persistent volume
├── secrets/firebase-admin.json
├── backup/
└── evidence/
```

Karena kode saat ini mengharapkan nama/path tertentu, buat secret mount ke path yang diharapkan atau ubah path menjadi environment variable sebelum image dipromosikan.

### 5.4 Dry run tanpa traffic publik

Gunakan baseline backup, bukan database produksi aktif:

- [ ] Jalankan container pada port internal sementara, misalnya 18000.
- [ ] Pastikan `/docs` dan `/openapi.json` dapat dibuka.
- [ ] Simpan `openapi.json` dari server lama dan baru, lalu diff. Seluruh path, method, request schema, response schema, dan status code harus kompatibel.
- [ ] Uji login dengan akun test hasil copy.
- [ ] Uji bearer token yang sudah ada melalui `GET /users/me`; token lama harus tetap valid.
- [ ] Uji `GET /devices/`, `/monitoring/`, `/notifications/`, dan `/sensor/?uid=<UID>`.
- [ ] Kirim satu payload IoT canary ke `POST /sensor/`, pastikan tepat satu row bertambah.
- [ ] Uji update FCM token dan notifikasi test pada akun/perangkat test.
- [ ] Pastikan background checker tidak membuat notifikasi duplikat setiap menit.
- [ ] Restart container dan pastikan data tetap ada di persistent volume.

## 6. Tahap A — final cutover Cloudflare

### 6.1 Checklist go/no-go

- [ ] Semua backup dan hash tervalidasi.
- [ ] Restore rehearsal berhasil.
- [ ] Device retry/spool telah dibuktikan.
- [ ] Image baru lulus smoke test.
- [ ] Kontrak OpenAPI lama dan baru tidak berubah secara breaking.
- [ ] Firebase Admin credential bekerja.
- [ ] Origin baru dapat diakses oleh host `cloudflared`.
- [ ] Rule rollback Cloudflare/origin lama sudah dicatat.
- [ ] Monitoring log HTTP, error rate, database size, disk, CPU, dan timestamp sensor tersedia.

### 6.2 Urutan final copy

1. Catat waktu mulai cutover dalam UTC dan WITA/WITA sesuai kebutuhan tim.
2. Pertahankan Cloudflare mengarah ke origin lama.
3. Bekukan operasi Android yang mengubah data.
4. Pantau request IoT terakhir dan konfirmasi perangkat mempunyai retry.
5. Hentikan Uvicorn lama secara graceful; jangan kill database saat transaksi aktif.
6. Jalankan checkpoint, integrity check, dan backup final:

```bash
cd /home/frey/FastAPI_SQLite/iot_server_4
sqlite3 aquanotes.db "PRAGMA wal_checkpoint(FULL); PRAGMA integrity_check;"
sqlite3 aquanotes.db ".backup '/home/frey/aquanotes-backup/aquanotes-final.db'"
sha256sum /home/frey/aquanotes-backup/aquanotes-final.db
```

7. Transfer `aquanotes-final.db` ke temporary path di LXC 101.
8. Verifikasi SHA-256 sumber dan tujuan identik.
9. Jangan menimpa file tujuan aktif. Tempatkan sebagai file baru, set owner/mode, lalu lakukan rename atomik sebelum container start.
10. Start container baru, tunggu health check, dan lakukan smoke test melalui origin internal.
11. Ubah service/origin Cloudflare Tunnel untuk hostname yang sama ke origin baru, misalnya `http://192.168.10.100:8000` (sesuaikan dengan posisi `cloudflared`).
12. Jangan mengubah public hostname atau menambahkan `/docs` sebagai prefix origin. `/docs` hanya endpoint verifikasi; origin harus tetap melayani root API.
13. Uji URL publik `/docs`, `/openapi.json`, login, bearer token lama, dan endpoint IoT.
14. Amati request perangkat aktif sampai masing-masing UID menghasilkan data baru di server baru.
15. Biarkan server lama mati tetapi utuh selama masa rollback; jangan hapus database atau credentialnya.

### 6.3 Validasi segera setelah cutover

- [ ] HTTP `/docs` dan `/openapi.json` = 200.
- [ ] `POST /sensor/` dengan canary valid = 200 dan menambah tepat satu row.
- [ ] UID tidak dikenal tetap memberi respons yang sama seperti server lama.
- [ ] Existing Android bearer token berhasil di `GET /users/me`.
- [ ] Login baru menghasilkan format token yang sama.
- [ ] Semua endpoint utama dan trailing slash tetap sama.
- [ ] Setiap device aktif memiliki `last_seen` baru dan status `online` sesuai intervalnya.
- [ ] FCM test diterima perangkat Android.
- [ ] Tidak ada lonjakan 4xx/5xx, timeout, atau duplicate notification.
- [ ] Row count tabel tidak berkurang dari snapshot final.

Simpan evidence setelah cutover: hash backup, row count, max ID/timestamp, hasil integrity check, OpenAPI diff, log request per UID, dan screenshot/status FCM test.

## 7. Rekonsiliasi data Tahap A

Bandingkan snapshot final lama dengan database baru sebelum menganggap migrasi selesai:

- Row count seluruh tabel.
- `max(id)` seluruh tabel ber-ID integer.
- `min(timestamp)` dan `max(timestamp)` untuk `sensor_data` dan `notifications`.
- Daftar UID device dan hubungan user/kolam/tambak.
- Jumlah auth token yang belum kedaluwarsa.
- Hash agregat per chunk untuk tabel besar, bukan hanya count.

Contoh pemeriksaan orphan:

```sql
SELECT count(*) FROM sensor_data s LEFT JOIN devices d ON d.id=s.device_id WHERE d.id IS NULL;
SELECT count(*) FROM auth_tokens a LEFT JOIN users u ON u.id=a.user_id WHERE u.id IS NULL;
SELECT count(*) FROM kolam k LEFT JOIN tambak t ON t.id=k.tambak_id WHERE k.tambak_id IS NOT NULL AND t.id IS NULL;
SELECT count(*) FROM notifications n LEFT JOIN users u ON u.id=n.user_id WHERE n.user_id IS NOT NULL AND u.id IS NULL;
```

Nilai orphan tidak boleh bertambah dibanding sumber. Jangan menghapus row orphan saat migrasi; catat dan perbaiki terpisah setelah layanan stabil.

## 8. Rollback Tahap A

Rollback sederhana hanya aman jika belum ada write baru di server baru.

### Sebelum write baru diterima

1. Arahkan Cloudflare kembali ke origin lama.
2. Start Uvicorn lama.
3. Verifikasi `/docs`, login, dan ingestion IoT.
4. Simpan database baru untuk analisis; jangan hapus.

### Setelah write baru diterima

Jangan langsung mengarahkan traffic ke database lama karena sensor/ubah data setelah cutover akan hilang. Pilih salah satu:

- Pertahankan traffic di server baru sambil memperbaiki issue, atau
- Hentikan write, ekspor delta dari database baru berdasarkan waktu/ID cutover, merge ke salinan database lama, validasi, lalu rollback.

Kriteria rollback yang disarankan:

- Error 5xx berkelanjutan atau ingestion sensor gagal untuk satu interval penuh.
- Token lama tidak dapat dipakai.
- Row count turun, relasi rusak, atau data baru tidak persisten setelah restart.
- FCM/background task menyebabkan kegagalan luas atau duplikasi masif.

## 9. Masa observasi Tahap A

- [ ] 0–2 jam: pantau setiap UID, 4xx/5xx, latency, log SQL, FCM, CPU/RAM/disk.
- [ ] 24 jam: verifikasi tidak ada gap sensor melebihi interval normal + toleransi retry.
- [ ] 72 jam: verifikasi backup otomatis dan lakukan satu restore test.
- [ ] 7 hari: jika stabil dan rekonsiliasi final disetujui, server lama boleh diarsipkan; backup tetap mengikuti kebijakan retensi.

Jangan memulai Tahap B sebelum Tahap A stabil minimal 72 jam dan seluruh evidence disetujui.

## 10. Tahap B — persiapan aplikasi untuk PostgreSQL

Perubahan kode yang diperlukan sebelum menyentuh data produksi:

- [ ] Baca `DATABASE_URL` dari environment.
- [ ] Hanya berikan `check_same_thread=False` bila scheme adalah SQLite.
- [ ] Hapus `sqlite3.connect`, `PRAGMA`, dan `ALTER TABLE` ad-hoc dari startup.
- [ ] Tambahkan Alembic dan buat baseline migration dari schema yang benar-benar ada.
- [ ] Tambahkan driver PostgreSQL yang dipilih, misalnya `psycopg[binary]`, ke lockfile.
- [ ] Lengkapi dependency runtime dan pin versi yang telah diuji.
- [ ] Tambahkan health endpoint yang memeriksa koneksi database tanpa membocorkan secret.
- [ ] Pastikan timestamp diperlakukan konsisten; project saat ini memakai `datetime.utcnow()` tanpa timezone.
- [ ] Pastikan sequence PostgreSQL di-reset ke `max(id)+1` setelah import.
- [ ] Pastikan boolean, datetime, unique constraint, index, nullable, dan foreign key setara.
- [ ] Matikan auto-create/migration implisit di startup setelah Alembic menjadi sumber schema.
- [ ] Jalankan tetap satu worker sampai background task dipindahkan ke scheduler/worker tunggal dengan locking.

Gunakan database dan user khusus aplikasi:

```text
postgresql+psycopg://<app_user>:<secret>@192.168.10.110:5432/<database>
```

Jangan menaruh URL lengkap tersebut di Git atau log.

## 11. Tahap B — rehearsal SQLite ke PostgreSQL

1. Ambil backup SQLite terbaru dari LXC 101 menggunakan SQLite backup API.
2. Restore ke environment staging terisolasi.
3. Buat schema PostgreSQL melalui Alembic.
4. Import dengan tool/script yang eksplisit dan repeatable. Jangan mengandalkan `Base.metadata.create_all()` sebagai migrator data.
5. Pertahankan primary key dan token string persis seperti sumber.
6. Reset sequence setiap tabel integer setelah import.
7. Jalankan seluruh validasi count, ID, timestamp, orphan, unique, dan aggregate hash.
8. Jalankan contract/smoke test yang sama dengan Tahap A.
9. Uji rollback `DATABASE_URL` ke salinan SQLite staging.
10. Catat durasi final export/import untuk menentukan maintenance window produksi.

Lakukan rehearsal minimal dua kali dari backup bersih. Script migrasi harus idempotent atau selalu menarget database PostgreSQL kosong yang baru dibuat.

## 12. Tahap B — cutover database produksi

Gunakan pola maintenance singkat yang sama:

1. Pastikan device retry/spool tetap aktif.
2. Bekukan write Android.
3. Stop aplikasi di LXC 101 secara graceful.
4. Buat SQLite backup final, integrity check, hash, dan baseline counts.
5. Import ke database PostgreSQL kosong menggunakan script yang sudah lulus rehearsal.
6. Reset sequences dan jalankan rekonsiliasi penuh.
7. Start versi aplikasi PostgreSQL dengan `DATABASE_URL` secret.
8. Jalankan smoke test internal dan publik.
9. Buka kembali write Android dan pantau seluruh UID.
10. Simpan SQLite final sebagai rollback snapshot immutable.

Jika durasi import hasil rehearsal lebih panjang daripada kemampuan retry IoT, jangan gunakan maintenance sederhana. Implementasikan ingestion queue/relay atau migrasi delta/CDC yang sudah diuji terlebih dahulu.

## 13. Matriks penerimaan akhir

| Area | Bukti lulus |
|---|---|
| Hostname | Android dan IoT tetap memakai `aeraseaku.inkubasistartupunhas.id` |
| API contract | OpenAPI diff tidak menunjukkan breaking change |
| IoT | Semua UID aktif mengirim setelah cutover; tidak ada gap di luar toleransi retry |
| Android session | Token lama berhasil tanpa login ulang |
| Data | Count, max ID/timestamp, relasi, dan aggregate checks cocok |
| FCM | Token tetap tersimpan dan notifikasi test diterima |
| Persistence | Restart container tidak menghilangkan data |
| Background task | Satu eksekusi checker; tidak ada notifikasi ganda |
| Backup | Backup final memiliki hash, integrity check, dan restore test |
| Rollback | Origin lama dan prosedur rekonsiliasi tersedia selama observasi |
| Security | Password lama dirotasi; secret tidak berada di Git/image |

## 14. Keputusan yang masih harus diisi sebelum eksekusi

- [ ] Lokasi proses `cloudflared` dan bentuk ingress config saat ini.
- [ ] Nama service/container final dan health-check URL.
- [ ] Hasil konfirmasi retry/spool firmware setiap tipe perangkat IoT.
- [ ] Daftar endpoint/base URL yang tertanam pada aplikasi Android rilis aktif.
- [ ] Versi source dan `pip freeze` yang benar-benar berjalan di server lama.
- [ ] Jumlah row serta max ID/timestamp produksi sesaat sebelum rehearsal.
- [ ] RTO/RPO yang disetujui dan durasi maintenance maksimum.
- [ ] Retensi backup dan lokasi salinan ketiga.
- [ ] PIC go/no-go, PIC Cloudflare, PIC database, dan PIC validasi Android/IoT.

## 15. Ringkasan urutan aman

```text
Audit + rotasi secret
  → buktikan retry IoT
  → backup online + restore rehearsal
  → build identik dengan SQLite
  → dry run + OpenAPI/token/FCM test
  → final stop/backup/hash
  → start origin baru
  → pindahkan Cloudflare origin (hostname tetap)
  → rekonsiliasi + observasi 72 jam
  → baru siapkan dan rehearsal PostgreSQL
  → cutover database terpisah
```

## 16. Tahap 1 assignment history (22 Agustus 2026)

Perubahan ini dilakukan sebelum migrasi PostgreSQL/TimescaleDB agar histori
kepemilikan mulai tercatat sekarang tanpa mengubah kontrak firmware atau mobile.

- `device_assignments` menyimpan periode user, kolam, dan tambak.
- `sensor_data.assignment_id` bersifat nullable dan tidak diekspos melalui API.
- Backfill mengatribusikan data lama ke pemilik serta kolam saat migrasi.
- Data milik device tanpa pemilik tetap tersimpan dengan `assignment_id = NULL`.
- Remove menutup assignment; claim dan move membuat assignment baru.
- Monitoring, sensor history, export, dan threshold hanya membaca assignment user
  yang berhak.

Rehearsal pada salinan production:

- 1.126.147 row sensor sebelum dan sesudah migrasi.
- 1.084.420 row ter-backfill; 41.727 row device tanpa pemilik tetap `NULL`.
- 20 assignment aktif, nol mismatch device, nol FK error, integrity `ok`.
- Durasi 12 detik termasuk backup yang dibuat script.
- OpenAPI path dan schema tetap sama; `/export/csv` hanya bertambah kewajiban
  bearer token untuk menutup akses histori lintas user.

Gate sebelum deploy:

- [x] Backup online konsisten dan SHA-256 tersimpan.
- [x] Rehearsal pada salinan production berhasil.
- [x] IoT canary pada staging mendapat HTTP 200 dan tepat satu row baru.
- [x] Field `assignment_id` tidak muncul pada request/response API.
- [x] Bearer token lama dan `/monitoring` staging mendapat HTTP 200.
- [ ] Backup final sesaat sebelum migrasi production.
- [ ] Migrasi production, build image, dan smoke test.
- [ ] Observasi setiap UID aktif dan error 5xx/database lock.
