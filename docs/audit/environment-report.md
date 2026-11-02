# Environment Report — Universal Web Acquisition Engine (Audit G0)

**Tanggal audit:** 2026-10-20
**Metode:** verifikasi langsung (perintah dijalankan, hasil dicatat) — bukan asumsi.
**Catatan:** laporan versi sebelumnya memuat konteks proyek lain (agentic-cli) dan Python 3.11.9 — tidak akurat dan diganti seluruhnya dengan fakta terverifikasi berikut.

## 1. Lingkungan Eksekusi

| Fakta | Nilai terverifikasi | Bukti |
|---|---|---|
| Platform | Termux Android via PRoot-Distro, tanpa root | `uname -a` → `Linux localhost 6.17.0-PRoot-Distro` |
| Arsitektur | **aarch64** (ARM64) | `uname -m` |
| Python (Termux) | **3.14.6** — `/data/data/com.termux/files/usr/bin/python` | `python --version` |
| Python (PRoot) | 3.14.4 — `/usr/bin/python3` | `python3 --version` |
| pip | 25.1.1 (terikat ke Python PRoot 3.14) | `pip --version` |
| Storage | 226 GB total, **22 GB bebas** (91% terpakai) | `df -h /` |
| RAM | 7.566 MB total, ~3.430 MB tersedia | `free -m` |
| Jaringan | OK — HTTPS ke `example.com` sukses dari 4 transport | smoke test G0-3 |

> **Peringatan penting:** ada **dua binary Python**. Proyek (pytest, kode `src/`) berjalan di Python **Termux 3.14.6**; `pip` default menunjuk ke Python **PRoot 3.14.4**. Instalasi paket harus eksplisit memilih interpreter target, jika tidak paket akan terpasang di environment yang salah.

## 2. Hasil G0-3 — Matriks Transport (Python Termux 3.14.6, aarch64)

| Transport | Import | Smoke test (GET example.com) | Versi |
|---|---|---|---|
| httpx | ✅ | ✅ 200 (4.047 ms) | 0.28.1 |
| requests | ✅ | ✅ 200 (824 ms) | 2.33.0 |
| urllib3 | ✅ | ✅ 200 (533 ms) | 2.7.0 |
| aiohttp | ✅ | ✅ 200 (641 ms) | 3.14.1 |
| niquests | ❌ tidak terpasang | — | — |
| curl_cffi | ❌ tidak terpasang | — | — |
| pycurl | ❌ tidak terpasang | — | — |

**Dukungan:** h2 4.4.1 ✅, socksio 1.0.0 ✅, websockets 15.0.1 ✅, certifi 2026.5.20 ✅, charset_normalizer 3.4.9 ✅, **brotli ❌**.
**Parsing:** bs4 4.15.0 ✅, lxml 6.1.3 ✅; selectolax ❌, parsel ❌.
**Library browser** (playwright, selenium, nodriver, camoufox, patchright, seleniumbase, pyppeteer, DrissionPage, pyvirtualdisplay): **❌ semuanya belum terpasang** di Python Termux.

## 3. Hasil G0-4 — Jalur Browser Android

| Jalur | Status | Bukti |
|---|---|---|
| Chromium headless (PRoot) | ✅ **TERVERIFIKASI JALAN** | `/usr/bin/chromium` 151.0.7922.34; `--headless=new --no-sandbox --disable-gpu --dump-dom` sukses, exit=0 (warning udev tidak fatal) |
| Cache browser Playwright | ✅ binary sudah terunduh | `~/.cache/ms-playwright/`: chromium-1234, chromium-1243, chromium_headless_shell-1234/1243, firefox-1538, webkit-2336, ffmpeg-1011 |
| `chromium-browser` (PRoot) | Wrapper ke Playwright chromium | shell script → `~/.cache/ms-playwright/chromium-1234/chrome-linux/chrome` |
| Firefox (PRoot) | ❌ rusak — wrapper snap | output `snap install firefox`; screenshot gagal |
| Firefox (Termux) | ✅ terpasang, launch belum diuji | dpkg: `firefox:aarch64 157.0.1` |
| Xvfb | ✅ tersedia | `/usr/bin/Xvfb`, `xvfb-run` |
| Node.js | ✅ v26.5.0 + npm (nvm) | `which node npm` |
| adb | ✅ tersedia (Termux) | `/data/data/com.termux/files/usr/bin/adb` |
| Android runtime | ✅ terakses dari PRoot | `/system/bin/am`, `/system/bin/pm` |
| chromedriver / geckodriver | ❌ tidak ada | `which` |

## 4. Jawaban Klarifikasi "Lebih dari 120 Modul" (Lampiran L.1 INSTRUCTION.md)

Dengan bukti terukur:

- **A** (file/modul Python milik Botasaurus): **113 file `.py`** di snapshot repo (618 file tracked); **38 `.py`** di paket `botasaurus` terpasang.
- **B/C** (paket + seluruh dependensi venv): **357 paket** (dist-info) di `/root/botasaurus-venv`, 47 direktori top-level site-packages.

→ Klaim "lebih dari 120 modul" terkonfirmasi sebagai **B/C** (357 paket venv), **bukan** kode Botasaurus sendiri (113 file). Konsekuensi: target kompetitif harus berbasis kemampuan, bukan mengejar jumlah modul.

## 5. Perbedaan Lingkungan venv Botasaurus vs Python Termux (relevan untuk benchmark adil)

| Paket | venv botasaurus | Python Termux |
|---|---|---|
| brotli | 1.2.0 ✅ | ❌ |
| requests | 2.34.2 | 2.33.0 |
| PyVirtualDisplay | 3.0.0 ✅ | ❌ |
| httpx | 0.28.1 | 0.28.1 (sama) |

Benchmark differential (UWAE vs Botasaurus) harus menyamakan dulu content-encoding (brotli) dan versi library, atau mencatat perbedaannya secara eksplisit.
