# Pemulihan Aquanotes setelah listrik padam

## Temuan 7 November 2026

- Publik web/API mengembalikan 502. API berulang kali exit code 3; log `Network is unreachable` saat menghubungi PostgreSQL `192.168.10.65:5432`.
- PostgreSQL dapat menerima query `SELECT 1`, bukan dalam recovery, dan `transaction_read_only=off` melalui Tailscale. Ini bukan pemeriksaan integritas seluruh database.
- Bridge Docker `stage2_default` turun; metadata jaringan API kosong dan endpoint web tidak memiliki IP. Kedua container masih memiliki restart policy `unless-stopped`; restart berulang saja tidak memulihkan kondisi tersebut.
- Host Proxmox juga mengalami tekanan I/O 90–99%; proses filesystem/journal/Compose tertahan `D-state`. Thin pool sekitar 4%, root sekitar 5% terpakai, SMART PASSED dengan pending/uncorrectable/reallocated 0. SMART PASSED tidak menyingkirkan masalah performa SSD.
- Pengujian sementara WBT=0 dan scheduler=none tidak memulihkan aplikasi. Keduanya dikembalikan: WBT 2000 dan scheduler mq-deadline. Cache flush, fsync, dan journaling tidak dinonaktifkan.
- Restart Docker terkontrol dilakukan satu kali. Daemon kembali masuk proses restore dan menghapus stale sandbox; selama pemeriksaan terakhir proses restore masih tertahan I/O. Bootstrap sudah diantrekan setelah Docker siap. Ini belum merupakan bukti aplikasi pulih.

## Pencegahan yang dipasang

Pada Proxmox `192.168.10.10`, seluruh guest tetap `onboot=1`:

1. CT165 database: `startup order=10,up=30`.
2. CT166 MQTT: `startup order=20,up=15`.
3. CT164 Docker: `startup order=30,up=30`.

Urutan shutdown dibalik oleh Proxmox. Jeda boot bukan pengganti pemeriksaan readiness.
Backup konfigurasi awal: `/root/aquanotes-power-recovery-20261107/{164,165,166}.conf`.

Pada CT164:

- `/etc/systemd/system/docker.service.d/aquanotes-network-ready.conf`: Docker menunggu network-online dan IP LAN `192.168.10.64/24` pada eth0; kegagalan startup dicoba kembali dengan jeda 15 detik.
- `/etc/systemd/system/aquanotes-bootstrap.service`: pemulihan sekali per boot, setelah Docker/network siap; retry pemeriksaan readiness setiap 30 detik.
- `/usr/local/sbin/aquanotes-bootstrap.py`: bila API/web sudah sehat, tidak melakukan perubahan. Jika belum, memeriksa listener database, mengambil Compose/image dari metadata deployment yang benar-benar terpasang, memverifikasi nama dan ID image, lalu recreate hanya komponen Aquanotes yang tidak sehat.
- Tidak build atau pull image, mengubah secrets, menghapus volume, mengubah database, atau men-deploy source dari laptop. Tag berubah atau release file hilang ditolak, bukan ditebak.
- Marker `/run/aquanotes-bootstrap/api` dan `web` membatasi recreate satu kali per komponen per boot. Retry berikutnya hanya memeriksa readiness. Docker restart policy tetap menangani crash aplikasi; bukan timer restart tanpa batas.

## Pemeriksaan

```sh
systemctl status docker aquanotes-bootstrap --no-pager
journalctl -u aquanotes-bootstrap -n 40 --no-pager
docker ps -a --filter name=stage2-
curl --max-time 8 -fsS http://192.168.10.64:8000/health
curl --max-time 8 -fsS http://192.168.10.64:8080/api/health
```

Health API juga menjalankan `SELECT 1`. Setelah kedua pemeriksaan lokal lulus, periksa domain publik, login, monitoring, serta freshness telemetry. Jangan menyatakan pulih hanya karena container berstatus running.

Saat maintenance yang sengaja menghentikan aplikasi, hentikan/disable unit bootstrap agar boot berikutnya tidak menghidupkan kembali layanan yang sedang ditahan:

```sh
systemctl disable --now aquanotes-bootstrap.service
```

Re-enable setelah maintenance. Untuk mengulang bootstrap secara manual pada boot yang sama, periksa penyebabnya dan state marker terlebih dahulu; jangan menghapus marker lalu memaksa recreate berulang saat storage masih macet.

## Rollback

- Disable unit bootstrap di atas. Tidak perlu menghapus container atau data.
- Pindahkan hanya `/etc/systemd/system/docker.service.d/aquanotes-network-ready.conf` ke lokasi backup, kemudian `systemctl daemon-reload`. Perubahan efektif saat Docker berikutnya dimulai; jangan restart semua layanan hanya untuk membatalkan drop-in.
- Konfigurasi awal ketiga CT tidak memiliki `startup`; bila memang ingin mengembalikannya, gunakan `pct set <ID> --delete startup` untuk ID 164, 165, 166. Tetap pertahankan `onboot=1`. Jangan menimpa seluruh konfigurasi CT dari backup jika ada perubahan lain setelah insiden.

## Batasan

Software startup tidak dapat menjamin pemulihan jika SSD/host terus mengalami I/O stall. Pengguna mengonfirmasi UPS sudah ada tetapi tanpa koneksi monitoring. Diperlukan UPS atau modul kompatibel dengan monitoring USB/jaringan dan shutdown otomatis sebelum baterai habis; pemasangan tidak bisa dilakukan tanpa perangkat yang mendukungnya. Evaluasi SSD, jalur SATA, kernel, dan backup dalam maintenance terpisah bila stall berulang. Jangan melakukan hard power-cycle berulang atau menonaktifkan fsync/journal untuk mengejar performa.

Referensi: [Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/), [Linux block queue ABI](https://kernel.org/doc/html/latest/admin-guide/abi-stable.html).

Tes lokal: `python -m unittest discover -s tests -p test_power_recovery.py -v` (5 tes, termasuk tidak recreate layanan sehat, penolakan downgrade/tag berubah, serta batas sekali per boot).

## Maintenance lanjutan 7 November 2026

- Backup PostgreSQL pertama berhasil dialirkan langsung ke laptop, 22.594.796 byte, `pg_dump` exit 0. Folder `secrets/backups` dibatasi ACL Windows dan di-ignore Git. Jangan menggunakan berkas `.partial` dari percobaan yang tidak selesai.
- Checksum SHA-256 hasil transfer diverifikasi ulang; `pg_restore --list` berhasil membaca 186 entri, termasuk TABLE DATA `users` dan `sensor_data`. Belum dilakukan restore penuh ke database uji.
- Baseline jumlah pengguna/perangkat dan ID sensor terakhir tersimpan di folder backup privat untuk pemeriksaan setelah layanan kembali.
- Pelepasan WBT sementara membantu proses penyalinan/shutdown; tidak dibuat permanen, dan tidak menonaktifkan fsync atau cache flush. Reboot mengembalikan setting kernel default.
- Semua enam LXC berhenti melalui shutdown graceful, dengan `forceStop=0`, sebelum `systemctl reboot --no-block` diterima host sekitar 14:53 GMT+8. Tidak melakukan hard power-cycle.
- Pemeriksaan berikutnya belum dapat mengonfirmasi boot baru: host `.10` tidak menjawab ARP/ping maupun SSH dari Raspberry Pi dan laptop yang sudah terhubung ke `MTC_Group`. Router `.1` dan host lama `.11` tetap dapat diakses.
- Status aplikasi **belum pulih**. Diperlukan tampilan monitor/console host untuk membedakan shutdown yang tertahan, kegagalan boot/storage, atau interface jaringan yang belum aktif. Jangan mengasumsikan database rusak hanya karena host tidak dapat diakses.

Jika console sudah login, ambil keluaran read-only `uptime`, `ip -br address`, `ip route`, dan `systemctl --failed --no-pager`. Bila tertahan di BIOS/boot/kernel shutdown, kirim foto pesan tersebut sebelum mengambil tindakan power tambahan. Verifikasi baseline dan freshness telemetry tetap wajib setelah server kembali.
