# Implementasi OTA AquaNotes

Status terakhir: **OTA profil panel berhasil** pada `AER2023AQ0029`; canary `2.1.5-panel-canary` online dan telemetry normal. Jangan rollout ke fleet sebelum gate manual yang tersisa lulus.

## Komponen aktif

- Backend production menyediakan upload release bertanda tangan, publish, assignment, retry, cancel, download bertoken, status, dan audit log.
- Mosquitto memakai topic `devices/{uid}/ota/desired` (retained) dan `devices/{uid}/ota/status` (QoS 1).
- Firmware memakai partisi A/B, verifikasi SHA-256 + ECDSA P-256, self-test, dan rollback bootloader ESP-IDF.
- Dashboard admin tersedia pada menu firmware.
- Jalur HTTPS telemetry lama tetap aktif; OTA tidak mengubah kontrak mobile atau payload telemetry lama.

## Release hardware

| Release | Status | Catatan |
|---|---|---|
| `2.1.0-ota-baseline` | ready, tidak di-rollout | Baseline awal. |
| `2.1.1-ota-canary` | retired | Manifest 493 byte melebihi buffer MQTT 512 byte. Assignment dibatalkan sebelum download. |
| `2.1.2-ota-bootstrap` | known-good | Dipasang melalui COM5 ke AER2023AQ0029. Buffer MQTT 1024 byte; command retained dan laporan sukses sudah teruji. |
| `2.1.3-ota-canary` | retired | Salah menganggap unit panel memiliki baterai; assignment dibatalkan karena `LOW_BATTERY`. |
| `2.1.4-panel-bootstrap` | known-good | Dipasang melalui COM5; profil panel aktif dan LCD menampilkan `B:DC`. |
| `2.1.5-panel-canary` | canary sukses | OTA bertanda tangan berhasil tanpa kabel; assignment 5 `success`, telemetry kembali online. |

Artifact lokal berada di `Aquanotes_Frimware/aquanotes-triangle/release/<version>/`. Artifact production tidak boleh diganti setelah release dibuat; buat versi SemVer baru.

## Signing

- Algoritma: ECDSA P-256 + SHA-256.
- Key ID aktif: `b7aa2aa6e416c024`.
- Private key hanya berada di `D:\Aerasea\Aquanotes_Frimware\secrets\ota-signing-private.pem` dan tidak boleh masuk Git/server.
- Public key backend: `deployment/stage2/secrets/ota-signing-public.pem`.
- Public key firmware: `Aquanotes_Frimware/aquanotes-triangle/include/ota_signing_key.h`.

Build release:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 `
  -Version 2.1.5-panel-canary `
  -SigningKey D:\Aerasea\Aquanotes_Frimware\secrets\ota-signing-private.pem
```

## Operasi aman

1. Upload `.bin` dan `.sig`; pastikan hash, ukuran, key ID, dan status `ready` benar.
2. Pilih satu device meja sebagai canary. Jangan assign ke seluruh fleet.
3. Pastikan Wi-Fi lebih baik dari -75 dBm dan tidak sedang kalibrasi. Untuk profil `portable`, baterai juga wajib valid dan minimal 50%; profil `panel` tidak membaca ADC baterai.
4. Pantau urutan `assigned → downloading → downloaded → rebooting → pending_verify → success`.
5. Pastikan telemetry kembali masuk dan `current_firmware_version` berubah.
6. Stabilkan canary minimal 24 jam sebelum menambah batch.

Assignment aktif dapat dibatalkan dari dashboard/API. Pembatalan menghapus retained desired command; firmware yang sudah selesai menulis image tetap mengikuti mekanisme A/B.

## Backup dan rollback

- Backup DB sebelum OTA: `/var/backups/aquanotes/aquanotes-before-ota-20261004.dump` pada host database.
- Source backend fallback: `/srv/aquanotes-stage2/release-20261004-ota-stage1`.
- Release known-good hardware panel: `2.1.4-panel-bootstrap`.
- Rollback operasional dibuat sebagai assignment baru dengan `rollback=true`; jangan mengganti artifact sebuah versi.
- Jika first boot gagal sebelum image dinyatakan valid, bootloader kembali ke slot lama.

## Gate yang masih wajib

- [x] Build signed dan verifikasi signature.
- [x] Bootstrap A/B diflash melalui COM5.
- [x] MQTT retained command >512 byte diterima setelah buffer menjadi 1024 byte.
- [x] Status assignment dan versi firmware tercatat backend.
- [x] OTA `2.1.4-panel-bootstrap` ke `2.1.5-panel-canary` sukses pada profil panel tanpa battery gate.
- [ ] Uji putus daya saat download (image lama tetap boot).
- [ ] Uji reset pada first boot sebelum validasi (rollback otomatis ke known-good).
- [ ] Canary stabil 24 jam tanpa regresi telemetry/sensor.
- [ ] Private signing key mempunyai backup offline terenkripsi.

Rollout fleet tetap **ditahan** sampai semua gate manual tersebut dicentang.
