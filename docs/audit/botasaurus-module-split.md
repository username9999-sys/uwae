# Audit: Modul Botasaurus sendiri vs dependensi pihak ketiga

> Menjawab pertanyaan gerbang **TEXT.md §9 #1**: *"Berapa banyak modul Botasaurus yang merupakan kode proyek sendiri, dan berapa banyak dependensi pihak ketiga?"*
>
> Diukur 2026-10-31 langsung dari `/root/botasaurus-venv/lib/python3.14/site-packages` (metode di bagian bawah). Semua angka di bawah dihitung dari `RECORD` tiap paket dan isi file `.py` — bukan dari klaim.

## Jawaban singkat

| Kategori | Paket (dist-info) | File `.py` | Baris kode |
|---|---|---|---|
| **Milik Botasaurus sendiri** (nama paket mengandung `botasaurus`) | **6** | **144** | **59.768** |
| **Dependensi pihak ketiga** | **39** | **2.310** | **857.328** |
| **Total venv** | **45** | **2.454** | **917.096** |

**Rasio kode milik Botasaurus sendiri terhadap seluruh venv: 144/2.454 file (5,9%) dan 59.768/917.096 baris (6,5%).** Jadi ~94% kode yang berjalan saat Botasaurus dipakai sesungguhnya adalah dependensi pihak ketiga.

## Rincian per paket milik Botasaurus (6 paket, 144 file)

| Paket | Versi | File `.py` | Baris | Top-level module |
|---|---|---|---|---|
| `botasaurus_driver` | 4.0.101 | 82 | 49.599 | `botasaurus_driver` |
| `botasaurus` (inti) | 4.0.97 | 38 | 5.116 | `botasaurus` |
| `botasaurus_requests` | 4.0.38 | 16 | 3.747 | `botasaurus_requests` |
| `botasaurus_humancursor` | 4.0.83 | 5 | 887 | `botasaurus_humancursor` |
| `botasaurus_api` | 4.0.10 | 2 | 383 | `botasaurus_api` |
| `botasaurus_proxy_authentication` | 1.0.16 | 1 | 36 | `botasaurus_proxy_authentication` |

Catatan: paket terbesar justru **bukan** paket inti `botasaurus` (38 file), melainkan `botasaurus_driver` (82 file, 49.599 baris — 83% dari seluruh kode milik Botasaurus). Jadi "Botasaurus" sebagai produk lebih banyak kode di lapisan driver/browser-nya daripada di dekorator permintaannya.

## Dependensi pihak ketiga (39 paket, 38 top-level dir)

Top-level dir yang dihitung sebagai pihak ketiga (dari `RECORD` paket non-botasaurus): `anyio, bota, bs4, certifi, charset_normalizer, click, close_chrome, cloudpickle, deprecated, et_xmlfile, gevent, geventhttpclient, greenlet, h11, httpcore, httpx, idna, javascript_fixes, joblib, lxml, markdown_it, mdurl, numpy, openpyxl, pip, psutil, pygments, pytweening, pyvirtualdisplay, requests, rich, soupsieve, urllib3, websocket, wrapt, zope` — 2.310 file `.py`, 857.328 baris.

Yang paling besar di antaranya: `numpy`, `lxml`, `gevent`, `openpyxl`, `rich` — semuanya jauh melampaui kode milik Botasaurus sendiri.

## Koreksi terhadap environment-report.md

`docs/audit/environment-report.md:58` mencatat **"357 paket (dist-info)"**. Angka itu **salah** bila dibaca sebagai jumlah paket: `ls *.dist-info` di site-packages menghasilkan **45**, dan `pip list` menghasilkan 47 baris (45 paket + header). Total **file** (semua ekstensi) di site-packages adalah 6.106 — juga bukan 357. Angka 357 tidak cocok dengan metrik apa pun yang dapat direproduksi (bukan paket, bukan file, bukan baris). Koreksi: **45 paket terinstal**, dengan rincian 6 milik Botasaurus / 39 pihak ketiga seperti di atas. Koreksi ini dicatat di ADR-028; environment-report.md tidak ditimpa (audit historis tetap utuh, koreksi mengikutinya).

## Metode (reproduksibel)

1. Paket = direktori `*.dist-info` di `site-packages` (45 buah).
2. Milik Botasaurus = nama dist-info mengandung `botasaurus` (6 buah).
3. Top-level module per paket dibaca dari `RECORD` (kolom pertama, hanya path `.py`).
4. File `.py` dan baris dihitung dengan `rglob('*.py')` pada top-level module tersebut; baris = jumlah `splitlines()` per file (termasuk komentar dan baris kosong — konsisten untuk kedua sisi perbandingan).
5. Dependensi pihak ketiga = paket non-botasaurus; top-level-nya dikurangi irisan dengan top-level milik Botasaurus (tidak ada irisan di sini).

## Implikasi untuk perbandingan kompetitif

Klaim lama "lebih dari 120 modul" (INSTRUCTION.md lampiran L) ternyata mengacu pada **kode milik Botasaurus sendiri** (144 file), bukan pada venv. Setelah diukur: 144 file milik Botasaurus vs 2.310 file dependensi yang ia pakai. Artinya, apa yang "dimiliki" Botasaurus sebagai produk relatif kecil; sebagian besar kemampuan datang dari pustaka eksternal (requests/httpx untuk HTTP, lxml/bs4 untuk parsing, gevent/joblib untuk konkurensi, dan driver CDP untuk browser). Ini mendukung keputusan ADR-024: target kompetitif harus berbasis **kemampuan terukur**, bukan mengejar jumlah modul.
