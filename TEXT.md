
Saya ingin melanjutkan proyek **Universal Web Acquisition Engine**, sebuah framework Python berbasis CLI dan plugin yang dirancang untuk mengungguli Botasaurus.

### Tujuan utama
Membangun sistem scraping universal dengan cakupan seluas mungkin untuk:
- Menemukan sumber dan tautan file dari website.
- Mengunduh berbagai jenis file, termasuk file tanpa ekstensi.
- Mengidentifikasi format, memverifikasi integritas, dan mengekstrak konten melalui plugin.
- Mendukung HTTP, browser automation, halaman JavaScript, autentikasi, sesi, caching, concurrency, retry, dan pemulihan pekerjaan.
- Mengembangkan Adaptive Access Engine untuk mendeteksi Cloudflare, CAPTCHA, rate limiting, dan kondisi anti-bot; memilih strategi akses yang sesuai; serta mengelola verifikasi dan pemulihan sesi.
- Mengukur performa dan membandingkan hasil dengan Botasaurus melalui benchmark yang dapat direproduksi.

### Arsitektur yang telah dirancang
1. Core dan Job Orchestrator.
2. Discovery Engine.
3. HTTP Transport dan Browser Adapter.
4. Adaptive Access Engine.
5. Session Manager dan Challenge Workflow.
6. Streaming Acquisition Engine.
7. Raw Artifact Storage dan Integrity Verification.
8. File Identification Registry.
9. Plugin-based Extraction Engine.
10. Export, Observability, Security, dan Benchmark Suite.

### Keputusan desain
- Python-first dan CLI-first.
- Arsitektur modular, extensible, dan berbasis capability registry.
- File mentah harus tetap tersimpan meskipun formatnya belum dikenal atau ekstraksi gagal.
- Format baru harus dapat ditambahkan melalui plugin tanpa mengubah core.
- Jangan menetapkan daftar format file sebagai batas permanen.
- Jangan mengklaim mengungguli Botasaurus sebelum ada hasil benchmark yang valid.
- Untuk CAPTCHA dan anti-bot, prioritaskan analisis teknis, pemilihan strategi, pemulihan sesi, dan pengujian terotorisasi.

### Langkah berikutnya
Mulai dari **Phase 0 — Source Audit and Competitive Benchmark** untuk mempelajari source code Botasaurus, mengidentifikasi keunggulan dan kekurangannya, menyusun matriks kompetitif, serta menentukan arsitektur dan urutan implementasi yang paling tepat.

Lanjutkan dari konteks ini tanpa mengulang pembahasan dari awal. Berikan analisis teknis yang mendalam dan rencana implementasi yang dapat langsung digunakan oleh AI coding agent.
…

Memproses selama 30s
Universal Web Acquisition Engine
Phase 0 — Source Audit and Competitive Benchmark
Fokus tahap ini adalah membangun dasar teknis yang dapat dipertanggungjawabkan sebelum menulis core framework. Kita akan mempelajari implementasi Botasaurus, memisahkan kemampuan yang benar-benar tersedia dari klaim dokumentasi, mengidentifikasi peluang arsitektur yang lebih kuat, lalu menghasilkan spesifikasi implementasi yang dapat langsung dijalankan oleh AI coding agent.

Prinsip utamanya: jangan mencoba mengalahkan Botasaurus dengan sekadar menambahkan lebih banyak fitur. Bangun sistem yang lebih terukur, lebih extensible, lebih tangguh terhadap kegagalan, dan mampu memperoleh serta memproses artefak dengan cara yang dapat diverifikasi.

Phase 0 harus menghasilkan bukti dan keputusan arsitektur, bukan sekadar dokumen perencanaan.

1. Definisi keberhasilan Phase 0
Source audit Botasaurus

Memetakan struktur kode, alur eksekusi, transport HTTP, browser automation, pengelolaan sesi, retry, concurrency, serta mekanisme unduh dan ekstraksi yang benar-benar diimplementasikan.

Competitive capability matrix

Membandingkan Botasaurus dan Universal Web Acquisition Engine berdasarkan kemampuan yang telah diverifikasi, bukan hanya berdasarkan daftar fitur.

Reproducible benchmark

Menyiapkan skenario uji, dataset, metrik, lingkungan, baseline, dan format hasil yang dapat diulang serta dibandingkan secara adil.

Architecture decisions

Menghasilkan ADR yang menetapkan batas modul, kontrak plugin, model artefak, kebijakan akses adaptif, dan urutan implementasi berdasarkan temuan audit.

Kriteria keluar Phase 0: setiap temuan penting memiliki bukti sumber atau hasil eksperimen; setiap gap memiliki prioritas; dan Phase 1 memiliki acceptance criteria yang bisa diuji otomatis.

2. Temuan awal audit Botasaurus
Sumber utama yang akan dijadikan objek audit adalah repositori resmi Botasaurus: GitHub — omkarcloud/botasaurus.

Dokumentasi dan metadata paket menunjukkan bahwa Botasaurus bukan sekadar pembungkus HTTP. Ia menggabungkan browser automation, request berbasis HTTP, cache, parallel execution, retry, pengelolaan driver, serta output hasil scraping. Metadata setup.py yang ditemukan mencantumkan versi 4.0.97 dan sejumlah dependensi khusus. Ini adalah titik awal audit, bukan jaminan bahwa versi tersebut merupakan versi terbaru yang dirilis di semua kanal. 

GitHub
+2

2.1 Matriks kemampuan awal
Status berikut adalah penilaian awal dari dokumentasi publik. Status ini belum berarti seluruh implementasinya telah diperiksa langsung.

Area

Kemampuan Botasaurus yang terdokumentasi

Implikasi untuk proyek kita

HTTP acquisition

Request adapter dengan konfigurasi proxy dan retry

Pisahkan transport dari kebijakan pengambilan

Browser automation

Driver berbasis Chrome/Selenium dengan helper navigasi dan interaksi

Browser harus menjadi adapter, bukan ketergantungan seluruh core

JavaScript

Menggunakan browser untuk halaman yang membutuhkan eksekusi JavaScript

Sediakan pemilihan transport berdasarkan kebutuhan halaman

Concurrency

Parallel execution dan asynchronous queue

Ukur throughput beserta biaya memori dan overhead browser

Caching

Cache hasil tugas berdasarkan input

Bedakan cache hasil ekstraksi dari cache respons HTTP dan artefak

Retry

Retry yang dapat dikonfigurasi, termasuk jeda

Gunakan kebijakan retry berdasarkan kategori kegagalan

Sesi

Penggunaan kembali driver dan cookies

Modelkan siklus hidup sesi secara eksplisit

Deteksi challenge

Helper deteksi bot dan alur browser khusus untuk sejumlah challenge

Buat klasifikasi challenge yang dapat diuji, dengan jalur pemulihan terkontrol

Penyimpanan file mentah

Belum terbukti sebagai pipeline artefak universal dari bukti yang diperiksa

Audit lebih lanjut; jadikan raw artifact sebagai objek kelas utama

Identifikasi format

Belum terbukti memiliki registry identifikasi format yang extensible

Evaluasi kebutuhan signature detection dan plugin identifikasi

Ekstraksi plugin

Memiliki mekanisme scraping yang extensible pada level tugas, tetapi kontrak plugin ekstraksi universal belum terbukti

Pisahkan discovery, acquisition, identification, dan extraction

Pemulihan pekerjaan

Ada penanganan crash dan error tugas; jaminan durable checkpoint belum terbukti

Uji apakah pekerjaan dapat dilanjutkan setelah proses dihentikan

Dokumentasi Botasaurus secara khusus menjelaskan cache hasil tugas, parallel execution, reuse_driver, dan penanganan error. Itu adalah kemampuan yang sudah mapan dan perlu dijadikan baseline, bukan fitur yang boleh kita abaikan. 

GitHub
+2

2.2 Di mana kita berpotensi unggul?
Saya melihat lima peluang pembeda yang layak diuji.

A. Acquisition terpisah dari extraction

Respons yang berhasil diunduh tetap menjadi artefak meskipun formatnya tidak dikenal, parser gagal, atau plugin tidak tersedia. Hasil ekstraksi dapat dibuat ulang tanpa mengunduh sumber lagi.

B. File-first, bukan extension-first

Penentuan format menggunakan gabungan signature, MIME, metadata, struktur internal, dan hasil pemeriksaan konten. Nama file dan ekstensi menjadi petunjuk, bukan kebenaran mutlak.

C. Durable job orchestration

Status pekerjaan, checkpoint, retry terklasifikasi, dan idempotensi memungkinkan pekerjaan dilanjutkan setelah crash atau proses Termux dihentikan.

D. Capability-based plugin registry

Transport, detector, extractor, exporter, dan access handler mendaftarkan kapabilitas melalui kontrak yang tervalidasi, tanpa menambahkan cabang khusus format ke core.

E. Benchmark yang mengukur hasil akhir

Ukur bukan hanya halaman per detik, tetapi juga tautan yang ditemukan, artefak yang berhasil disimpan, integritas file, akurasi identifikasi, keberhasilan ekstraksi, dan biaya sumber daya.

Penting: kelima poin ini adalah hipotesis keunggulan, bukan klaim bahwa Botasaurus tidak mampu melakukannya. Kita perlu mengujinya melalui audit source code dan benchmark.

2.3 Hal yang harus diperiksa di source code
Jangan langsung menyimpulkan kelemahan dari dokumentasi atau jumlah dependensi. Untuk setiap subsistem, coding agent harus menelusuri jalur dari API publik sampai implementasi konkret.

Dependency graph: modul internal, dependensi pihak ketiga, integrasi browser, serta kode yang bergantung pada sistem operasi.

Execution lifecycle: pembuatan tugas, scheduling, retry, cancellation, error propagation, cleanup dan shutdown.

HTTP lifecycle: redirect, timeout, streaming, penanganan Content-Length, transfer encoding, partial response, serta respons HTTP error.

Browser lifecycle: startup, reuse, cookies, storage, timeout, crash recovery, dan penutupan proses.

Cache correctness: cache key, invalidation, perubahan sesi, metadata yang sensitif, serta perilaku saat cache rusak.

Failure semantics: apakah kegagalan dicatat, ditelan, dilempar kembali, atau menyebabkan seluruh batch berhenti.

File acquisition: penentuan nama file, file tanpa ekstensi, respons berukuran besar, checksum, dan pemulihan unduhan parsial.

Access challenges: deteksi halaman challenge, status autentikasi, rate limiting, dan alur verifikasi manual.

Satu temuan yang layak dijadikan target verifikasi adalah isu publik Botasaurus mengenai timeout Cloudflare bypass dan infinite retry pada kegagalan resolusi DNS. Isu tersebut merupakan sinyal untuk menyusun regression test, bukan bukti bahwa seluruh rilis mengalami masalah yang sama. 

GitHub

3. Eksekusi audit source code
Lakukan audit terhadap snapshot repositori yang tetap dan dapat diidentifikasi. Jangan mengaudit master yang berubah-ubah tanpa mencatat commit SHA.

Langkah 1 — Ambil snapshot dan metadata
Perintah berikut ditujukan untuk Termux atau lingkungan Linux dengan Git dan Python tersedia.

pkg install git python -y
mkdir -p ~/universal-web-acquisition/audit
cd ~/universal-web-acquisition/audit

git clone https://github.com/omkarcloud/botasaurus.git botasaurus
cd botasaurus

git rev-parse HEAD
git status --short
git log -1 --format='%H%n%cI%n%s'
python -VV
git ls-files > ../botasaurus-tracked-files.txt

Jika repositori sudah ada, jangan melakukan clone ulang atau mengubah checkout pengguna. Buat salinan audit terpisah atau gunakan worktree tersendiri.

Catat hasil perintah berikut dalam laporan:

git ls-files | wc -l
git ls-files '*.py' | wc -l
git ls-files '*test*' | wc -l
git ls-files 'pyproject.toml' 'setup.py' 'setup.cfg' \
  'requirements*.txt' 'Pipfile' 'poetry.lock'

Jumlah file adalah statistik snapshot, bukan ukuran kualitas atau kompleksitas keseluruhan.

Langkah 2 — Petakan arsitektur dan dependensi
git ls-files
git grep -nE \
  'def |class |@browser|@request|@task|retry|cache|parallel|async_queue'

Jika rg tersedia, gunakan pencarian yang lebih nyaman:

rg -n \
  'requests\.get|session\.get|iter_content|stream=|Content-Length|Content-Disposition|hashlib|sha256|os\.replace|fsync' \
  .

rg -n \
  'ThreadPoolExecutor|ProcessPoolExecutor|asyncio|Queue|Semaphore|retry|backoff|cache|sqlite|checkpoint|resume' \
  botasaurus docs

Tidak ditemukannya pola tertentu bukan bukti bahwa kemampuan itu tidak ada: implementasi mungkin berada dalam dependensi eksternal, memakai nama berbeda, atau memanggil API secara tidak langsung.

Buat peta dependensi dengan kategori:

Core framework.

HTTP request dan networking.

Browser dan driver.

Task scheduling dan concurrency.

Cache serta penyimpanan.

Output dan integrasi eksternal.

Utilitas, platform, dan lifecycle.

Testing, fixtures, dan tooling.

Periksa metadata paket dan dependensi yang dikunci secara terpisah. Misalnya, setup.py yang ditemukan mencantumkan requests, joblib, beautifulsoup4, lxml, dan sejumlah paket Botasaurus khusus. Ketergantungan ini perlu dipetakan sampai ke fungsi yang menggunakannya sebelum kita memutuskan apakah harus mengadopsi atau menggantinya. 

GitHub
+1

Langkah 3 — Gunakan bukti berlapis
Setiap klaim dalam laporan harus memiliki salah satu status berikut.

Status

Arti

VERIFIED_SOURCE

Implementasi ditemukan dan jalurnya ditelusuri

VERIFIED_TEST

Perilaku didukung tes yang relevan

VERIFIED_EXPERIMENT

Perilaku teramati pada eksperimen yang tercatat

DOCUMENTED_ONLY

Disebutkan dokumentasi, belum diverifikasi

NOT_FOUND

Tidak ditemukan pada area source yang sudah diperiksa

UNKNOWN

Bukti belum memadai atau belum diuji

Untuk setiap temuan NOT_FOUND, sertakan ruang lingkup pencarian dan dependensi yang belum diaudit. Dengan demikian, coding agent tidak mengubah ketidakpastian menjadi klaim kelemahan.

4. Matriks kompetitif yang akan menjadi sumber keputusan
Buat berkas docs/benchmark/competitive-matrix.md dengan struktur berikut.

Dimensi

Pengujian

Metrik utama

Link discovery

HTML biasa, sitemap, redirect, pagination, tautan bersarang

Precision, recall, waktu

HTTP acquisition

Respons kecil, besar, redirect, timeout, range request

Success rate, throughput

Browser acquisition

Halaman statis dan JavaScript-heavy

Keberhasilan, waktu, peak RAM

File identification

Ekstensi benar, salah, hilang, MIME tidak sesuai

Accuracy, unknown rate

Integrity

File lengkap, terpotong, berubah saat transfer

Deteksi kerusakan

Extraction

Format teks, dokumen, arsip, dan format tambahan melalui plugin

Success rate, kualitas hasil

Retry dan recovery

Gangguan jaringan, crash, proses dihentikan

Recovery rate, duplikasi

Cache

Cold run, warm run, invalidation

Cache hit rate, penghematan waktu

Concurrency

Beban bertahap dengan batas resource yang sama

Throughput, latency, RAM

Session handling

Login yang sah, sesi kedaluwarsa, autentikasi gagal

Keberhasilan dan pemulihan

Access challenges

HTTP 429, halaman challenge, CAPTCHA pada lingkungan uji

Akurasi klasifikasi, recovery outcome

Extensibility

Penambahan plugin tanpa modifikasi core

Waktu integrasi, tes kontrak

Portability

Termux Android dan Linux yang didukung

Keberhasilan instalasi dan fitur

Observability

Error, retry, cache, transfer, plugin

Kelengkapan event dan metrik

Gunakan tiga kolom implementasi untuk setiap dimensi: Botasaurus, Universal Engine, dan Evidence. Tambahkan pula Gap, Priority, Confidence, dan Next Experiment.

Aturan perbandingan
Jalankan benchmark dengan input dan kondisi jaringan yang sebanding.

Pisahkan pengukuran cold-cache dan warm-cache.

Jangan mencampurkan waktu download dengan waktu ekstraksi.

Catat versi Python, OS, CPU, RAM, versi dependensi, konfigurasi browser, serta commit kedua implementasi.

Laporkan median dan persentil latency, bukan hanya rata-rata.

Catat kegagalan, timeout, retry, serta konsumsi sumber daya; jangan hanya melaporkan kasus sukses.

Jalankan pengulangan yang cukup dan sertakan variasi hasil.

Gunakan situs milik sendiri, fixture lokal, atau lingkungan pengujian yang diizinkan agar hasil dapat direproduksi.

Target akhir Phase 0 bukan angka kemenangan tertentu. Targetnya adalah protokol yang memungkinkan kita menentukan apakah suatu perubahan benar-benar meningkatkan kemampuan sistem.

5. Desain benchmark yang dapat langsung diimplementasikan
Benchmark harus terdiri dari dua lapisan: microbenchmark komponen dan end-to-end benchmark.

Lapisan A — Component benchmarks
Mengisolasi penyebab performa dan kegagalan.

Discovery: ekstraksi URL dari HTML, sitemap, dan redirect.
Transfer: streaming, throughput, retry, dan penyimpanan parsial.
Identification: signature, MIME, ekstensi, dan format tidak dikenal.
Extraction: waktu parser, kualitas hasil, dan kegagalan plugin.
Orchestration: scheduling, concurrency, cancellation, dan recovery.
Lapisan B — End-to-end benchmarks
Mengukur kemampuan memperoleh hasil yang benar dari awal hingga akhir.

Temukan semua tautan yang memenuhi kriteria fixture.
Ambil konten atau file dari sumber yang ditentukan.
Simpan artefak mentah beserta metadata dan checksum.
Identifikasi format dan jalankan plugin yang sesuai.
Verifikasi keluaran terhadap ground truth.
Hentikan proses secara terkontrol dan uji kelanjutan pekerjaan.
5.1 Dataset fixture
Buat tests/fixtures/acquisition/ berisi manifest dan server uji lokal. Fixture harus mencakup:

HTML dengan tautan relatif dan absolut.

Redirect, pagination, serta sitemap.

Respons dengan Content-Disposition dan tanpa nama file.

File tanpa ekstensi dan ekstensi yang salah.

MIME yang tidak sesuai dengan isi file.

Respons chunked dan transfer yang terputus.

Respons 404, 429, 500, timeout, dan kegagalan DNS simulasi.

Dokumen valid, dokumen rusak, dan format yang belum memiliki plugin.

Halaman JavaScript yang baru menampilkan konten setelah interaksi.

Halaman autentikasi dan challenge simulasi.

Jangan menggunakan fixture sintetis sebagai satu-satunya bukti. Setelah pengujian deterministik lulus, tambahkan pengujian terotorisasi pada lingkungan nyata dengan kondisi dan hasil yang dicatat.

5.2 Definisi metrik
Gunakan rumus yang konsisten untuk kedua sistem.

Discovery Recall
=
tautan relevan yang ditemukan
seluruh tautan relevan dalam ground truth
Discovery Recall= 
seluruh tautan relevan dalam ground truth
tautan relevan yang ditemukan
​
 
Artifact Success Rate
=
artefak yang lengkap dan valid
artefak yang diharapkan
Artifact Success Rate= 
artefak yang diharapkan
artefak yang lengkap dan valid
​
 
Extraction Success Rate
=
hasil ekstraksi yang memenuhi validasi
artefak yang seharusnya dapat diekstrak
Extraction Success Rate= 
artefak yang seharusnya dapat diekstrak
hasil ekstraksi yang memenuhi validasi
​
 
Tambahkan:

Bytes per second dan files per second.

Median, p95 latency, serta durasi total.

Peak RSS dan konsumsi disk.

Jumlah retry per pekerjaan.

Recovery success rate setelah gangguan.

Duplicate acquisition rate.

Plugin load dan contract-test success rate.

Jangan menyamakan HTTP 200 dengan keberhasilan akuisisi. File yang terpotong, halaman challenge yang tersimpan sebagai PDF, atau HTML error yang diberi nama .zip tidak boleh dihitung sebagai artefak berhasil tanpa validasi yang sesuai.

6. Arsitektur target yang perlu divalidasi melalui ADR
Arsitektur sepuluh subsistem yang sudah kita sepakati tetap menjadi arah proyek. Phase 0 harus mengubahnya menjadi kontrak konkret, tanpa terburu-buru membuat seluruh implementasi.

CLI / Configuration

Commands · Policies · Profiles

Core + Durable Job Orchestrator

Job state · Scheduling · Cancellation · Recovery

Discovery Engine

URLs · Links · Sitemaps

Adaptive Access Engine

Signals · Policies · Recovery

HTTP Adapter

Streaming · Retry

Browser Adapter

JavaScript · Session

Artifact Pipeline

Raw storage → Integrity → Identification registry

Plugin Extraction Engine

Validators · Extractors · Exporters

Cross-cutting services

Session manager · Cache · Observability · Security · Benchmark suite

Diagram ini adalah hipotesis arsitektur, bukan keputusan implementasi final. ADR harus mengonfirmasi setiap batas modul dan aliran datanya berdasarkan hasil audit.

Kontrak inti yang wajib ditetapkan
Job: identitas stabil, input, policy, status, checkpoint, dan hasil.

DiscoveryResult: URL ditemukan, sumber penemuan, URL induk, dan metadata.

AcquisitionResult: status transfer, respons, jumlah byte, dan referensi artefak.

ArtifactManifest: lokasi penyimpanan, ukuran, checksum, waktu akuisisi, serta metadata sumber.

IdentificationResult: kandidat format, bukti signature, MIME, confidence, dan status identifikasi.

ExtractionResult: referensi input, plugin dan versinya, keluaran, validasi, serta error terstruktur.

AccessAssessment: sinyal challenge, kategori kegagalan, confidence, dan rekomendasi kebijakan.

PluginDescriptor: ID stabil, versi, kapabilitas, dependensi, dan kontrak kompatibilitas.

Setiap objek harus memiliki aturan serialisasi dan evolusi skema. Jangan menyimpan seluruh state pekerjaan hanya di memori proses.

Prinsip penyimpanan
Raw artifact disimpan terpisah dari metadata pekerjaan dan hasil ekstraksi. Gunakan ID artefak yang stabil serta checksum untuk memverifikasi integritas. Metadata harus memungkinkan penelusuran:

job → discovery result → acquisition → artifact → identification → extraction → export

Bila format belum dikenal atau plugin gagal, pipeline berhenti pada tahap yang gagal tanpa menghapus artefak yang valid.

Prinsip Adaptive Access Engine
Pisahkan tiga hal yang sering tercampur:

Detection: mengamati status HTTP, redirect, pola halaman challenge, CAPTCHA, status autentikasi, dan rate limiting.

Policy: menentukan apakah harus retry, menunggu, menggunakan adapter lain, meminta verifikasi pengguna, atau menghentikan pekerjaan.

Recovery: melanjutkan sesi yang valid, memperbarui autentikasi melalui mekanisme yang diizinkan, atau menandai pekerjaan untuk intervensi.

Khusus untuk challenge, keberhasilan tidak boleh disimpulkan hanya karena halaman berubah. Sistem harus memverifikasi bahwa konten tujuan benar-benar tersedia. CAPTCHA dan kontrol akses tidak boleh dianggap sebagai masalah yang selalu bisa diselesaikan dengan pergantian header, proxy, atau browser.

7. Urutan implementasi setelah Phase 0
Fase

Hasil utama

Gerbang kelulusan

0 — Audit

Source audit, competitive matrix, benchmark protocol, ADR

Bukti dan keputusan dapat ditinjau

1 — Core + Acquisition

CLI, job model, HTTP streaming, raw storage, integrity

Transfer dapat dilanjutkan dan hasil diverifikasi

2 — Discovery

Link extractor, sitemap, scope policy, deduplication

Recall dan precision sesuai fixture

3 — Identification + Plugins

Capability registry, format detection, extraction contracts

Plugin baru dapat ditambahkan tanpa mengubah core

4 — Browser + Sessions

Browser adapter, JavaScript, sesi dan autentikasi

Kontrak adapter lulus pada fixture

5 — Adaptive Access

Challenge classifier, retry policy, recovery workflow

Klasifikasi dan recovery terukur

6 — Durability + Scale

Persistent state, concurrency, cache, crash recovery

Tidak ada kehilangan atau duplikasi yang tidak terdeteksi

7 — Benchmark + Hardening

Perbandingan end-to-end, security, performance

Hasil bisa direproduksi dan klaim didukung data

Urutan ini bukan larangan mengerjakan hal lain. Ini adalah urutan dependensi teknis agar kita tidak membangun browser orchestration, plugin, dan retry di atas kontrak artefak yang belum stabil.

8. Instruksi siap pakai untuk AI coding agent
Salin instruksi berikut ke Claude Code atau Hermes dari direktori proyek yang akan digunakan. Instruksi ini membatasi scope Phase 0, bukan cakupan kemampuan akhir framework.

9. Pemeriksaan akhir sebelum memulai Phase 1
Gunakan checklist ini untuk memastikan agent benar-benar menyelesaikan audit, bukan sekadar menghasilkan Markdown panjang.

Phase 0 exit checklist
0/10

Snapshot Botasaurus dan commit SHA tercatat.

Peta dependensi mencakup kode internal dan dependensi eksternal yang relevan.

Temuan penting memiliki bukti source, test, atau eksperimen.

Capability matrix membedakan fakta dan hipotesis.

Benchmark memiliki ground truth dan skema hasil.

Pengukuran mencakup kebenaran hasil, kegagalan, latency, dan resource use.

Kontrak Job, ArtifactManifest, AcquisitionResult, dan plugin telah ditinjau.

ADR menyatakan alternatif, trade-off, dan keputusan yang masih terbuka.

Roadmap Phase 1 memiliki acceptance criteria yang dapat diuji.

Perubahan tidak merusak file atau keputusan proyek yang sudah ada.
Rekomendasi urutan kerja sekarang: jalankan Workstream A dan B terlebih dahulu, kemudian susun matriks kompetitif dari bukti yang terkumpul. Setelah itu, tetapkan benchmark dan ADR sebelum mengunci desain Phase 1.

Keunggulan Universal Web Acquisition Engine nantinya harus berasal dari pipeline akuisisi yang dapat dipulihkan, artefak yang bisa diverifikasi, plugin yang benar-benar independen, serta pengukuran yang jujur—bukan dari klaim kompatibilitas universal atau kemenangan benchmark yang belum dibuktikan.

Ini belum dapat mengalahkan botasaurus
Benar. Blueprint sebelumnya belum cukup untuk mengalahkan Botasaurus. Blueprint itu baru menetapkan proses audit dan arah arsitektur, tetapi belum membuktikan bahwa Universal Web Acquisition Engine memiliki keunggulan teknis yang cukup besar.

Masalah utamanya: kita masih merancang framework scraping yang lebih modular, padahal targetmu adalah membangun mesin akuisisi web yang mampu mengungguli Botasaurus secara terukur dalam cakupan, ketahanan, kemampuan pemulihan, extensibility, dan efisiensi.

Modularitas, plugin, dan dukungan lebih banyak format bukan otomatis keunggulan kompetitif. Kita harus menentukan apa yang akan membuat sistem ini benar-benar lebih baik, membuktikannya dengan eksperimen, lalu membangun kemampuan yang tidak dapat dicapai hanya dengan membungkus ulang library yang sudah ada.

1. Kita perlu mengubah strategi persaingan
Botasaurus sudah memiliki sejumlah kemampuan yang cukup matang: browser automation, request berbasis HTTP, konfigurasi proxy, stealth request, pemakaian ulang browser, parallel execution, cache, retry, dan penanganan error. Dokumentasi resminya juga menjelaskan pemilihan strategi request atau browser sesuai kebutuhan halaman. 

GitHub
+1

Karena itu, Universal Web Acquisition Engine tidak bisa menang hanya dengan menyediakan versi modular dari fitur-fitur tersebut.

Strategi yang lebih kuat adalah menjadikan proyek ini sebagai acquisition platform yang mengelola keseluruhan siklus hidup data web, bukan sekadar menjalankan fungsi scraping.

Lima keunggulan yang harus kita bangun dan buktikan
Portfolio
1. Acquisition Intelligence

Sistem membangun graf hubungan antara halaman, tautan, file, redirect, sesi, dan hasil akuisisi. Setiap hasil discovery dapat menghasilkan pekerjaan lanjutan berdasarkan kebijakan dan prioritas.

Modul 04: Akuisisi dan Duplikasi Data Forensik | digital-forensics
2. Universal Artifact Pipeline

Semua respons yang relevan dapat dipertahankan sebagai artefak mentah. Sistem mengidentifikasi format berdasarkan bukti, mengelola versi hasil ekstraksi, serta memungkinkan pemrosesan ulang tanpa mengunduh ulang.

Medium
3. Adaptive Acquisition Planner

Planner memilih HTTP, browser, penggunaan kembali sesi, penundaan, atau intervensi pengguna berdasarkan bukti dan biaya. Keputusan diperbarui ketika kondisi akses berubah, bukan menggunakan satu strategi tetap untuk semua URL.

Managed Deep Agents: the fastest way to ship a production deep agent
4. Durable Execution

Job, checkpoint, percobaan, dan artefak memiliki identitas stabil. Setelah crash, proses melanjutkan pekerjaan yang belum selesai tanpa mengulang semua langkah yang telah berhasil.

P95, P99, and Why Averages Lie – Zoyla
5. Evidence-Driven Optimization

Sistem menggunakan telemetry dan benchmark untuk menemukan bottleneck, mengevaluasi strategi yang berhasil, dan mengoptimalkan biaya akuisisi tanpa mengorbankan kelengkapan atau integritas hasil.

Ini adalah arah pembeda yang lebih kuat. Namun, semuanya masih berupa sasaran desain sampai implementasi dan hasil pengujian membuktikan manfaatnya.

2. Keputusan arsitektur yang lebih ambisius
Saya merekomendasikan perubahan fokus dari sepuluh subsistem yang berdiri berdampingan menjadi lima lapisan dengan satu aliran kerja terintegrasi.

Lapisan

Tanggung jawab utama

Intelligence

Discovery graph, klasifikasi halaman, pemilihan strategi, prioritas pekerjaan

Execution

HTTP, browser, sesi, concurrency, retry, cancellation

Artifact

Streaming, penyimpanan mentah, checksum, identifikasi format, deduplikasi

Knowledge

Plugin extraction, hasil terstruktur, provenance, pemrosesan ulang

Control plane

CLI, durable scheduler, policy engine, observability, benchmark

Perbedaan pentingnya adalah hubungan antarlapisan.

Contohnya, ketika sebuah halaman berisi 500 tautan:

Discovery menghasilkan kandidat URL dan hubungan dengan halaman induknya.

Planner mengelompokkan pekerjaan berdasarkan kebutuhan akses, prioritas, dan batas resource.

Execution memilih adapter yang sesuai.

Artifact layer menyimpan hasil transfer dan metadata integritasnya.

Identification menentukan plugin yang relevan.

Knowledge layer mengekstrak konten dan menyimpan provenance.

Planner menjadwalkan pekerjaan lanjutan jika artefak atau halaman mengandung sumber baru.

Scheduler mempertahankan status sehingga pekerjaan dapat dilanjutkan setelah kegagalan.

Dengan model ini, sistem bukan sekadar scraper yang memproses daftar URL. Sistem menjadi mesin yang mengelola siklus hidup akuisisi.

3. Jangan langsung membangun semuanya: lakukan competitive spike
Sebelum memutuskan arsitektur final, coding agent harus menjawab satu pertanyaan teknis:

Pada workload yang sama, bagian mana yang dapat dilakukan Botasaurus, bagian mana yang gagal atau kurang efisien, dan apa desain alternatif yang benar-benar memberikan hasil lebih baik?

Pilih enam eksperimen pembeda:

E1 — Artifact durability: proses dihentikan saat unduhan berjalan, kemudian dilanjutkan.

E2 — Unknown files: unduh file tanpa ekstensi dan file dengan MIME yang salah, kemudian identifikasi dan validasi isinya.

E3 — Reprocessing: ubah plugin ekstraksi dan proses ulang artefak yang sudah tersimpan tanpa transfer ulang.

E4 — Adaptive scheduling: bandingkan biaya dan keberhasilan HTTP-first dengan strategi browser-first pada fixture yang sama.

E5 — Failure isolation: satu URL mengalami timeout atau error permanen sementara pekerjaan lain harus tetap selesai.

E6 — Resource efficiency: bandingkan throughput, p95 latency, dan peak memory pada tingkat concurrency yang setara.

Eksperimen tersebut menguji area di mana arsitektur yang direncanakan berpotensi memberi nilai tambah. Hasilnya tetap harus dibandingkan dengan perilaku Botasaurus yang benar-benar tersedia, bukan dengan implementasi pembanding yang sengaja dibuat lemah.

4. Instruksi revisi untuk AI coding agent
Gunakan instruksi ini sebagai pengganti arahan Phase 0 sebelumnya jika tujuanmu adalah persaingan teknis, bukan sekadar menyelesaikan audit dokumentasi.

Kesimpulan
Kalau targetnya benar-benar mengalahkan Botasaurus, kita perlu mengejar keunggulan yang terukur pada tingkat sistem, bukan sekadar memperbanyak fitur scraping.

Langkah berikut yang paling bernilai adalah melakukan audit source dan menjalankan competitive spike secara bersamaan setelah baseline disiapkan. Dengan begitu, kita tidak menghabiskan waktu membangun arsitektur besar yang terlihat bagus di atas kertas tetapi belum terbukti lebih baik dalam praktik.

Saya rasa ini belum dapat mengalahkan nya botasaurus venv punya lebih 120 module
Saya paham maksudmu. Jika Botasaurus di dalam venv memiliki lebih dari 120 modul, sedangkan rancangan kita baru membahas beberapa subsistem besar, kita belum menunjukkan kedalaman implementasi yang sebanding.

Namun, ada satu hal penting: jumlah modul bukan ukuran langsung kekuatan framework, tetapi jumlah modul yang mengimplementasikan kemampuan nyata, saling terintegrasi, dan teruji merupakan indikator yang layak diaudit. Kita harus memeriksa 120+ modul tersebut, bukan menganggap semuanya sebagai modul internal Botasaurus. Sebagian mungkin berasal dari dependensi pihak ketiga.

1. Kita perlu membedah isi venv Botasaurus
Ada tiga kategori yang harus dipisahkan:

Kategori

Yang perlu dihitung

Modul milik Botasaurus

Source code framework yang benar-benar dikembangkan proyek

Dependensi pihak ketiga

Modul dari Selenium, Requests, parser, dan library lain

Modul internal pendukung

Utilitas, compatibility layer, helper, integrasi, dan implementasi pendukung

Kalau kita hanya menghitung seluruh modul yang dapat diimpor dari venv, hasilnya tidak menunjukkan berapa banyak kode yang benar-benar dimiliki Botasaurus.

Sebaliknya, kalau kita hanya menghitung file Python di direktori utama, kita bisa melewatkan kemampuan yang diimplementasikan melalui dependensi atau subpaket.

Target audit kita adalah mendapatkan peta lengkap modul, dependensi, tanggung jawab, hubungan antarmodul, dan kemampuan yang dihasilkan.

2. Jalankan audit kuantitatif di lingkungan Botasaurus
Jika virtual environment Botasaurus sudah tersedia, jalankan perintah berikut dari direktori proyeknya. Tidak perlu menginstal ulang dependensi.


# 1. Pastikan Python berasal dari venv yang benar
python -c 'import sys; print(sys.executable); print(sys.prefix)'

# 2. Lokasi instalasi Botasaurus
python -m pip show botasaurus

# 3. Inventaris distribusi dan dependensi
python -m pip list --format=json > venv-packages.json
python -m pip freeze > venv-freeze.txt

# 4. Hitung file Python pada source Botasaurus
python - <<'PY'
from importlib.metadata import distribution
from pathlib import Path

dist = distribution("botasaurus")
files = list(dist.files or [])

py_files = [
    f for f in files
    if str(f).endswith(".py")
]

print("Distribution:", dist.metadata["Name"])
print("Version:", dist.version)
print("Installed Python files:", len(py_files))

for f in py_files:
    print(f)
PY

Perintah terakhir menghitung file Python yang tercatat pada metadata distribusi terpasang, bukan seluruh modul yang tersedia dalam venv. Itu memberi kita baseline yang lebih relevan untuk membandingkan source framework.

Untuk mendapatkan gambaran jumlah modul pihak ketiga, kita perlu menginventarisasi distribusi yang terpasang dan memisahkan namespace yang dimiliki setiap distribusi.

3. Target Universal Web Acquisition Engine harus lebih luas dari sekadar 120 modul
Saya tidak menyarankan menetapkan target seperti 150 atau 200 modul sekarang. Kita harus mengukur kedalaman kemampuan yang benar-benar dibutuhkan.

Contoh peta modul yang layak dievaluasi:

Discovery subsystem

Multi-module
URL normalization, sitemap parsing, robots policy, link extraction, pagination, scope management, deduplication, discovery graph, frontier scheduling.

Transport subsystem

Multi-module
HTTP sessions, streaming, redirects, proxy configuration, timeout policies, retries, rate limiting, connection pooling, response classification, transport selection.

Artifact subsystem

Multi-module
Content-Disposition parsing, filename inference, signature detection, MIME reconciliation, hashing, integrity validation, partial downloads, deduplication, metadata manifests.

Execution subsystem

Multi-module
Job state machine, scheduling, worker pools, backpressure, cancellation, checkpoints, recovery, idempotency, concurrency control, failure isolation.

Extraction subsystem

Multi-module
Plugin discovery, capability registry, parser adapters, validation, provenance, extraction caching, reprocessing, output normalization, export adapters.

Adaptive access subsystem

Multi-module
Challenge classification, session state, authentication workflows, response signals, policy evaluation, cooldowns, manual verification, recovery decisions.

Setiap kelompok tersebut masih harus dipecah berdasarkan tanggung jawab nyata, kontrak, dan kebutuhan pengujian. Tidak perlu memaksakan jumlah modul yang sama untuk setiap kelompok.

4. Langkah yang paling tepat sekarang
Sebelum membuat blueprint baru, kita perlu mengaudit struktur nyata Botasaurus yang ada di lingkunganmu.

Apakah yang kamu maksud lebih dari 120 modul itu adalah:

A. Lebih dari 120 file atau modul Python milik Botasaurus.

B. Lebih dari 120 paket dan modul jika seluruh dependensi dalam venv ikut dihitung.

C. Lebih dari 120 modul yang kamu hitung dari direktori site-packages, tetapi belum dipisahkan berdasarkan pemiliknya.

Perbedaan ini penting karena akan menentukan metode audit, perbandingan arsitektur, dan cara kita menetapkan target implementasi Universal Web Acquisition Engine.

Ini belum lengkap https http htpx dan lainnya
Betul. Kita belum memasukkan keseluruhan lapisan transport dan ekosistem HTTP yang relevan. Menjadikan requests sebagai satu-satunya transport, lalu menambahkan browser adapter, tidak cukup untuk proyek dengan ambisi seperti ini.

Audit Botasaurus juga memperlihatkan bahwa keunggulannya bukan hanya browser. Repositori dan dokumentasinya menunjukkan integrasi dengan botasaurus-requests, bota, driver khusus, proxy authentication, serta komponen pendukung lainnya. 

GitHub
+1

Kita harus memperluas desain menjadi transport ecosystem dengan capability registry, bukan memilih satu library HTTP untuk seluruh pekerjaan.

1. HTTP transport ecosystem yang harus diaudit
HTTP client adapters

httpx, requests, aiohttp, urllib3, urllib.request, serta curl_cffi dan pycurl untuk mengevaluasi kemampuan libcurl. Masing-masing memiliki model concurrency, connection pooling, streaming, timeout, dan konfigurasi TLS yang berbeda.

HTTP protocol dan connection capabilities

HTTP/1.1, HTTP/2, HTTP/3 jika didukung stack yang dipilih, redirects, cookies, compression, proxy, TLS, connection reuse, dan range requests. Dukungan harus diverifikasi pada versi library dan lingkungan aktual.

Transport fingerprint dan akses

TLS handshake behavior, HTTP header behavior, serta karakteristik koneksi yang dapat memengaruhi kompatibilitas server. Evaluasi secara terpisah dari autentikasi, klasifikasi challenge, dan kebijakan akses.

Browser-backed acquisition

Chromium melalui Playwright atau adapter browser lain yang sesuai, termasuk pengambilan respons melalui konteks browser ketika halaman bergantung pada JavaScript atau sesi browser.

2. Matriks transport yang lebih lengkap
Ini kandidat untuk diaudit, bukan instruksi untuk menginstal semuanya sekaligus.

Transport

Peran yang dievaluasi

Pertimbangan utama

httpx

HTTP sinkron dan asinkron

API terpadu, pooling, streaming

requests

HTTP sinkron

Ekosistem luas dan kompatibilitas

aiohttp

HTTP asinkron

Concurrency dan streaming

urllib3

HTTP low-level

Pooling, retry, kontrol transport

urllib.request

Standard library

Fallback dengan dependensi minimal

curl_cffi

Transport berbasis libcurl

Dukungan protokol dan TLS impersonation pada konfigurasi yang tersedia

pycurl

Binding libcurl

Kontrol transfer dan integrasi libcurl

hrequests

Kandidat request dengan karakteristik browser

Kematangan, kompatibilitas, dan pemeliharaan dependensi

cloudscraper

Kandidat integrasi khusus challenge

Ruang lingkup dukungan dan batas efektivitas

Playwright

Browser acquisition

JavaScript, cookies, konteks browser, network events

Selenium / Botasaurus Driver

Browser automation

Kompatibilitas, lifecycle, dan kemampuan khusus driver

httpx, hrequests, dan cloudscraper juga disebut secara eksplisit dalam dokumentasi Botasaurus ketika membahas perbedaan request biasa dan request yang dirancang untuk kondisi akses tertentu. Itu alasan untuk menguji perbedaannya, bukan alasan untuk menganggap satu library selalu lebih unggul. 

GitHub
+1

3. Jangan memilih transport berdasarkan nama library saja
Universal Web Acquisition Engine membutuhkan kontrak seperti berikut:


from typing import Protocol, runtime_checkable
from collections.abc import AsyncIterator, Mapping


@runtime_checkable
class TransportAdapter(Protocol):
    @property
    def capabilities(self) -> frozenset[str]:
        ...

    async def send(
        self,
        request: "AcquisitionRequest",
    ) -> "AcquisitionResponse":
        ...

    async def aclose(self) -> None:
        ...


class AcquisitionRequest(Protocol):
    url: str
    method: str
    headers: Mapping[str, str]
    timeout: float


class AcquisitionResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]
    final_url: str

    def iter_bytes(self) -> AsyncIterator[bytes]:
        ...

Ini hanya sketsa kontrak untuk diskusi. Sebelum implementasi, kita perlu menentukan model kepemilikan response, cancellation, streaming, exception, cookies, autentikasi, dan lifecycle agar adapter tidak memiliki perilaku yang berbeda-beda secara tersembunyi.

Planner kemudian dapat memilih adapter berdasarkan kebutuhan nyata:

Transfer file besar → prioritaskan streaming dan efisiensi memori.

Banyak URL independen → evaluasi concurrency asinkron.

Server membutuhkan HTTP/2 → pilih adapter yang telah memverifikasi dukungan HTTP/2.

Halaman bergantung pada JavaScript → gunakan browser jika diperlukan.

Sesi browser diperlukan → gunakan konteks sesi yang sesuai.

Koneksi gagal → klasifikasikan penyebabnya sebelum memutuskan retry atau adapter alternatif.

Jangan berpindah-pindah transport secara membabi buta ketika server menolak permintaan. Kebijakan harus menghormati autentikasi, pembatasan akses, dan kondisi challenge.

4. Instruksi tambahan untuk Phase 0
Tambahkan workstream khusus bernama Transport Ecosystem Audit ke instruksi coding agent sebelumnya:

Inventarisasi semua transport dan protokol yang digunakan Botasaurus beserta dependensinya.

Audit httpx, requests, aiohttp, urllib3, curl_cffi, pycurl, hrequests, dan cloudscraper; evaluasi browser adapter secara terpisah.

Verifikasi kompatibilitas versi Python, Android/Termux, dependensi native, TLS, proxy, streaming, dan cancellation.

Bangun microbenchmark lokal dengan payload identik dan kondisi jaringan yang sama.

Uji konsistensi cookies, redirect, timeout, connection pooling, respons parsial, dan error propagation.

Catat biaya instalasi, RAM, ukuran dependensi, dan kendala platform.

Pilih adapter berdasarkan hasil dan kapabilitas, bukan popularitas atau jumlah fitur di README.

Hasil yang harus dihasilkan:

docs/audit/transport-ecosystem.md

docs/benchmark/transport-matrix.json

docs/benchmark/transport-results.json

docs/architecture/decisions/ADR-transport-selection.md

Satu catatan penting: HTTPX bukan nama lengkap dari seluruh lapisan HTTP. HTTP/2 dan HTTP/3 merupakan protokol, sedangkan HTTPX adalah implementasi klien HTTP. TLS fingerprint, browser automation, dan pemulihan challenge juga merupakan lapisan yang berbeda. Memisahkan semuanya akan membuat perbandingan lebih akurat.

Dengan tambahan ini, audit tidak lagi berhenti pada modul Botasaurus. Kita mulai memetakan seluruh ekosistem transport yang dapat menjadi fondasi mesin akuisisi, termasuk kemampuan, keterbatasan, dan biaya integrasinya. Itu baru dasar yang layak untuk menentukan bagaimana Universal Web Acquisition Engine bisa melampaui Botasaurus.

Ini belum cukup kuat untuk mengalahkan botasaurus banyak website modern dengan deteksi bot yang kuat
Kamu benar. Menambahkan httpx, curl_cffi, Playwright, dan beberapa library lain belum cukup untuk menghadapi website modern dengan sistem deteksi bot yang kuat. Itu hanya memperluas pilihan transport dan browser, bukan otomatis meningkatkan keberhasilan akses.

Tantangan sebenarnya adalah membuat mesin yang mampu memahami kondisi akses, memilih strategi yang tepat, mempertahankan sesi yang sah, mendiagnosis kegagalan, dan mengukur keberhasilan akuisisi secara berkelanjutan.

Website modern bisa mengevaluasi banyak sinyal sekaligus: karakteristik TLS dan HTTP, konsistensi sesi, perilaku JavaScript, cookies, reputasi IP, pola permintaan, pembatasan laju, dan interaksi pengguna. Sebagian kontrol berjalan di server, sebagian di browser, dan sebagian melalui layanan pihak ketiga. Mengganti satu HTTP client tidak menyelesaikan keseluruhan masalah.

Kita perlu menaikkan desain Universal Web Acquisition Engine dari sekadar framework scraping menjadi adaptive web acquisition platform dengan sistem diagnosis akses, orkestrasi browser, pengelolaan sesi, dan evaluasi strategi berbasis bukti.

Tujuannya bukan menjanjikan bahwa setiap website dapat ditembus. Tujuannya memaksimalkan keberhasilan pada sumber yang dapat diakses secara sah, mengenali penyebab kegagalan secara akurat, dan memilih pemulihan yang sesuai tanpa membuang waktu dan resource.

1. Sistem yang sebenarnya kita butuhkan
Saya akan memperluas desain menjadi delapan subsistem akses adaptif. Semuanya harus saling terintegrasi dengan core, bukan menjadi kumpulan plugin yang bekerja sendiri-sendiri.

Access Intelligence & Diagnostics

Mengamati respons, redirect, sesi, JavaScript, rate limit, dan challenge.

Adaptive Strategy Planner

Memilih strategi berdasarkan bukti, kapabilitas, biaya, dan hasil sebelumnya.

Transport Engine

HTTP clients, streaming, pooling, retry policy.

Browser Engine

JavaScript, cookies, navigasi, lifecycle, network events.

Session & Identity

Sesi terpisah, autentikasi, masa berlaku, pemulihan.

Challenge Workflow

Klasifikasi, verifikasi pengguna, dan penanganan hasil.

Durable Acquisition & Feedback

Artefak, job state, provenance, telemetry, dan evaluasi hasil.

A. Access Intelligence & Diagnostics
Subsistem ini tidak cukup hanya memeriksa kode status HTTP. Ia harus menggabungkan beberapa bukti:

Status HTTP, redirect chain, dan header respons.

MIME type, struktur halaman, serta konten error.

Indikator challenge dan kebutuhan autentikasi.

Status cookies dan masa berlaku sesi.

Kebutuhan rendering JavaScript.

Sinyal timeout, DNS, TLS, koneksi, dan rate limiting.

Perbedaan antara halaman tujuan yang berhasil dimuat dan halaman challenge yang hanya mengembalikan HTTP 200.

Hasilnya berupa objek diagnosis terstruktur, bukan sekadar success=True atau success=False.

Contoh kategori hasil: ACCESS_GRANTED, AUTH_REQUIRED, RATE_LIMITED, CHALLENGE_PRESENT, JAVASCRIPT_REQUIRED, NETWORK_FAILURE, CONTENT_INVALID, dan UNKNOWN.

Kategori tersebut harus memiliki bukti pendukung, confidence, serta alasan yang dapat diperiksa.

B. Adaptive Strategy Planner
Planner bertugas memilih langkah berikutnya berdasarkan diagnosis, bukan mengulang permintaan yang sama tanpa batas.

Contoh:

Kondisi

Strategi berikutnya

Halaman publik dapat diambil melalui HTTP

Gunakan HTTP untuk efisiensi

Konten baru tersedia setelah JavaScript berjalan

Gunakan browser adapter

Sesi autentikasi kedaluwarsa

Jalankan alur autentikasi resmi

Respons 429

Hormati Retry-After bila tersedia dan terapkan backoff

DNS atau koneksi gagal

Diagnosis jaringan sebelum retry

CAPTCHA atau challenge interaktif

Gunakan alur verifikasi yang diizinkan atau minta intervensi pengguna

Halaman berhasil dimuat tetapi isinya salah

Tandai sebagai kegagalan validasi konten

Planner juga harus mengetahui kapan harus berhenti. Mengulang terus-menerus pada challenge yang tidak berubah bukan adaptasi; itu pemborosan resource.

C. Session & Identity Manager
Sistem modern memerlukan pengelolaan sesi sebagai komponen tersendiri.

Kemampuan yang harus dirancang meliputi:

Isolasi sesi berdasarkan profil akses yang sah.

Siklus hidup cookies dan kredensial.

Penyimpanan rahasia melalui mekanisme yang sesuai dengan platform.

Pemulihan sesi yang kedaluwarsa.

Sinkronisasi state ketika HTTP dan browser digunakan dalam satu alur.

Pencatatan perubahan sesi tanpa membocorkan token atau cookies sensitif.

Pemisahan state antar-job agar satu sesi tidak mencemari pekerjaan lain.

Catatan penting: cookies tidak boleh disalin secara membabi buta antara browser dan HTTP client. Scope, domain, path, expiry, serta karakteristik autentikasi dapat membuat sesi tidak ekuivalen.

2. Lapisan tambahan yang sering terlewat
Jika kita ingin membangun platform yang benar-benar matang, saya akan menambahkan subsistem berikut di luar transport dan browser.

Troubleshoot with your Browser’s Developer Tools | Developers.SuiteCommerce
Browser Network Intelligence

Mengamati request yang dipicu halaman, redirect, kegagalan resource, console errors, dan perubahan navigasi. Tujuannya mendiagnosis ketergantungan JavaScript dan masalah sesi, bukan menghindari kontrol keamanan situs.

Building a Scalable Rate Limiting System: Token Bucket vs Leaky Bucket - DEV Community
Rate & Resource Governance

Mengelola concurrency per host, antrean, cooldown, anggaran waktu, anggaran browser, dan backpressure. Sistem harus dapat memperlambat atau menghentikan pekerjaan ketika sumber membatasi akses.

AI Escalation Protocols: How AI Systems Ask for Help | AI Incident Response
Failure Classification Engine

Memisahkan kegagalan jaringan, autentikasi, challenge, parsing, integritas file, dan kesalahan konfigurasi. Setiap kategori mempunyai kebijakan retry dan recovery tersendiri.

MPM Module - Take Control of ML and AI Complexity
Strategy Evaluation Engine

Menyimpan hasil strategi sebelumnya dan mengevaluasi apakah strategi tertentu meningkatkan keberhasilan, waktu, atau konsumsi resource pada kelas workload tertentu. Keputusan harus berdasarkan sampel yang cukup, bukan satu keberhasilan.

Ada batas arsitektur yang harus dipertahankan: sistem boleh mendiagnosis mekanisme deteksi bot dan mengukur hasilnya, tetapi tidak boleh mengasumsikan bahwa setiap challenge harus dilewati. CAPTCHA, kontrol akses, dan pembatasan eksplisit harus memiliki alur penanganan yang sah, termasuk verifikasi pengguna, API resmi, atau penghentian pekerjaan.

3. Mengapa daftar library tidak menyelesaikan masalah ini?
Kita dapat mengintegrasikan banyak transport, tetapi semuanya tetap bisa ditolak oleh server yang sama.

Lapisan

Yang dapat ditingkatkan

Yang tidak dijamin

HTTP client

Throughput, pooling, timeout, streaming

Akses ke sumber yang menolak permintaan

TLS/HTTP stack

Kompatibilitas protokol

Penerimaan oleh sistem deteksi

Browser automation

Rendering dan interaksi JavaScript

Berhasil melewati setiap challenge

Session manager

Konsistensi autentikasi dan pemulihan

Hak akses yang tidak dimiliki

Adaptive planner

Pemilihan strategi dan diagnosis

Keberhasilan universal

Proxy integration

Konektivitas dan routing yang diizinkan

Reputasi IP atau penerimaan akses

Plugin extraction

Cakupan format dan kualitas parsing

Kemampuan mengambil sumber yang tidak dapat diakses

Karena itu, ukuran kompetitif utama kita harus berupa verified acquisition rate: persentase target yang berhasil diakuisisi dengan konten yang benar-benar memenuhi ground truth, bukan persentase request yang mendapat respons.

4. Blueprint implementasi Adaptive Access Engine
Saya menyarankan struktur modul berikut sebagai kandidat awal. Nama dan batas finalnya harus diselaraskan dengan source audit dan konvensi repositori.


universal_web_acquisition/
├── core/
│   ├── job.py
│   ├── scheduler.py
│   ├── state_machine.py
│   ├── checkpoint.py
│   └── cancellation.py
├── discovery/
│   ├── crawler.py
│   ├── sitemap.py
│   ├── link_extractor.py
│   ├── scope_policy.py
│   └── discovery_graph.py
├── access/
│   ├── assessment.py
│   ├── evidence.py
│   ├── classifier.py
│   ├── planner.py
│   ├── policy.py
│   ├── retry_policy.py
│   └── recovery.py
├── transports/
│   ├── registry.py
│   ├── contracts.py
│   ├── httpx_adapter.py
│   ├── requests_adapter.py
│   ├── aiohttp_adapter.py
│   ├── curl_cffi_adapter.py
│   └── urllib3_adapter.py
├── browser/
│   ├── registry.py
│   ├── lifecycle.py
│   ├── navigation.py
│   ├── network_observer.py
│   └── context_manager.py
├── sessions/
│   ├── manager.py
│   ├── cookie_store.py
│   ├── auth_provider.py
│   ├── expiry.py
│   └── secret_redaction.py
├── challenges/
│   ├── detectors/
│   ├── workflow.py
│   ├── user_verification.py
│   └── outcome_validator.py
├── artifacts/
│   ├── streaming.py
│   ├── storage.py
│   ├── integrity.py
│   ├── identification.py
│   └── manifest.py
├── plugins/
│   ├── registry.py
│   ├── contracts.py
│   ├── loader.py
│   └── validation.py
├── observability/
│   ├── events.py
│   ├── metrics.py
│   └── tracing.py
└── benchmarks/
    ├── fixtures/
    ├── scenarios/
    ├── runner.py
    └── reporting.py
Jangan membuat semua file tersebut sekaligus. Sebagian baru diperlukan setelah kontrak inti dan kebutuhan aktualnya diverifikasi. Tujuan struktur ini adalah menunjukkan kedalaman domain yang harus dipertimbangkan, bukan menetapkan jumlah file sebagai sasaran.

5. Roadmap untuk benar-benar bersaing
Tahap A — Competitive reconnaissance

Audit source Botasaurus, dependensi transport, driver browser, alur challenge, dan pengujian yang sudah tersedia. Catat versi dan bukti perilaku.

Tahap B — Access test laboratory

Bangun server fixture untuk HTTP biasa, JavaScript, sesi kedaluwarsa, rate limiting, respons challenge simulasi, serta kegagalan jaringan. Setiap skenario mempunyai ground truth.

Tahap C — Multi-transport execution

Implementasikan kontrak transport, streaming, response lifecycle, session policy, dan pengukuran biaya. Pilih adapter berdasarkan benchmark.

Tahap D — Browser and session orchestration

Integrasikan browser yang sesuai, network observation, autentikasi, pengelolaan konteks, serta pemulihan sesi.

Tahap E — Adaptive diagnostics and planning

Implementasikan evidence collection, classification, policy evaluation, retry, cooldown, intervensi pengguna, dan validasi hasil.

Tahap F — Durable acquisition

Hubungkan access engine ke job scheduler, checkpoint, artifact store, integrity verification, dan plugin extraction.

Tahap G — Competitive validation

Jalankan workload identik melawan Botasaurus. Publikasikan hasil menang, seri, kalah, dan belum teruji secara terpisah.

6. Acceptance criteria yang membuktikan peningkatan
Jangan menggunakan jumlah library atau jumlah modul sebagai kriteria kemenangan.

Metrik

Kriteria evaluasi

Verified acquisition rate

Konten yang diperoleh benar dibanding ground truth

Challenge classification

Precision, recall, dan false-positive rate

Recovery success

Pekerjaan yang pulih setelah kegagalan terkontrol

Session continuity

Keberhasilan alur autentikasi yang sah

Resource efficiency

Throughput dibanding peak RAM dan CPU

Tail latency

Median dan p95 pada workload setara

Artifact integrity

Kemampuan mendeteksi transfer terpotong atau konten salah

Plugin extensibility

Integrasi plugin baru tanpa modifikasi core

Portability

Tes instalasi dan fitur yang lulus pada lingkungan target

Untuk setiap metrik, tetapkan baseline Botasaurus dan target peningkatan setelah pilot benchmark. Jangan menentukan angka kemenangan sebelum distribusi hasil dan variasi pengukuran diketahui.

7. Instruksi final untuk AI coding agent
Kesimpulan: untuk menghadapi website modern, kita harus membangun sistem yang mampu mendiagnosis kondisi akses dan memilih tindakan berikutnya secara cerdas, bukan hanya menggabungkan banyak library. Itulah bagian yang paling layak menjadi fokus diferensiasi Universal Web Acquisition Engine.

Langkah berikutnya adalah menguji desain tersebut terhadap source Botasaurus dan fixture modern yang terkontrol, kemudian menggunakan hasilnya untuk menentukan implementasi yang benar-benar memberi keunggulan.

Ini masih kurang
Benar. Masalahnya bukan sekadar blueprint sebelumnya kurang banyak modul. Kita belum merancang sistem yang cukup mendalam untuk bersaing dengan Botasaurus pada website modern yang memiliki JavaScript kompleks, proteksi berlapis, sesi dinamis, pembatasan trafik, dan mekanisme deteksi otomatis. Menambahkan httpx, curl_cffi, Playwright, atau ratusan modul sekalipun tidak otomatis menyelesaikan masalah tersebut.

Kita perlu mengubah pendekatan dari membangun scraper dengan banyak library menjadi membangun platform akuisisi web adaptif yang dapat mengukur kondisi akses, memilih strategi, mengamati hasil, memulihkan kegagalan, dan membuktikan keunggulannya melalui pengujian terukur.

1. Lapisan kemampuan yang masih belum dirancang
01. Web Environment Intelligence

Sistem tidak hanya memeriksa status HTTP. Sistem mengumpulkan bukti mengenai redirect, struktur DOM, perubahan konten, kebutuhan JavaScript, jenis respons, kegagalan jaringan, dan indikasi challenge.

Hasil: diagnosis beserta tingkat keyakinan dan bukti pendukung.

02. Adaptive Strategy Engine

Memilih strategi berdasarkan bukti: HTTP sinkron, HTTP asinkron, browser, sesi autentikasi yang sah, penundaan, atau verifikasi pengguna. Keputusan dievaluasi ulang setelah setiap percobaan.

Hasil: strategi dipilih berdasarkan kondisi, bukan daftar fallback statis.

03. Multi-Transport Execution Fabric

Kontrak adapter untuk httpx, requests, aiohttp, urllib3, curl_cffi, dan transport lain yang memang tersedia serta layak dipelihara. Masing-masing memiliki kapabilitas, batasan, dependensi, dan hasil pengujian sendiri.

Hasil: transport dapat ditambahkan tanpa mengubah logika inti.

04. Browser Runtime Intelligence

Pengelolaan browser, context, navigasi, network events, DOM readiness, unduhan, popup, iframe, service worker, dan kegagalan renderer. Browser dipilih ketika memang diperlukan, bukan untuk setiap URL.

Hasil: penggunaan browser lebih terukur dan kegagalannya dapat didiagnosis.

05. Session Continuity & Access Recovery

Siklus hidup cookie dan token, kedaluwarsa sesi, autentikasi resmi, isolasi identitas sesi, penyimpanan rahasia, serta alur verifikasi pengguna. Challenge yang tidak dapat diselesaikan secara otomatis tidak boleh dianggap berhasil hanya karena browser terbuka.

Hasil: status sesi dan hasil pemulihan dapat diverifikasi.

06. Durable Acquisition & Artifact Intelligence

Unduhan streaming, checkpoint, resume jika server mendukung, validasi ukuran, hash, identifikasi format melalui signature, deduplikasi, dan pemrosesan ulang artifact tanpa mengunduh ulang.

Hasil: konten tetap dapat dipulihkan ketika ekstraksi gagal atau format belum dikenal.

07. Competitive Evaluation & Learning

Benchmark berulang, klasifikasi penyebab kegagalan, perbandingan strategi, pengukuran penggunaan sumber daya, serta penyimpanan hasil eksperimen. Sistem hanya mengubah kebijakan berdasarkan bukti yang cukup.

Hasil: peningkatan performa dapat dibuktikan dan direproduksi.

2. Yang membuatnya benar-benar kompetitif
Ada beberapa subsistem tambahan yang tidak boleh hilang dari rancangan.

Subsistem

Kemampuan yang harus dibuktikan

Discovery graph

Sitemap, pagination, canonical URL, link dinamis, deduplikasi, batas domain

Content validation

Membedakan halaman asli, halaman kosong, login, error, dan challenge

Protocol capability registry

Mencatat dukungan HTTP/1.1, HTTP/2, HTTP/3, streaming, proxy, dan TLS sesuai kemampuan adapter

Access policy engine

Memutuskan apakah akses dilanjutkan, ditunda, memerlukan autentikasi, atau harus berhenti

Retry and recovery controller

Backoff, Retry-After, batas percobaan, checkpoint, dan pemulihan proses

Resource governor

Batas concurrency, memori, bandwidth, jumlah browser, dan disk

Plugin contract system

Registrasi, validasi, versi, isolasi kegagalan, serta kompatibilitas plugin

Observability

Event terstruktur, trace per job, metrik per strategi, dan redaksi kredensial

Failure corpus

Kumpulan kasus kegagalan nyata dan fixture lokal untuk regresi

Differential benchmark

Membandingkan platform kita dengan Botasaurus menggunakan target, kondisi, dan ukuran keberhasilan yang sama

Catatan penting: HTTP/2 atau HTTP/3, fingerprint TLS, browser automation, dan penggunaan proxy merupakan kapabilitas berbeda. Dukungan terhadap suatu protokol tidak membuktikan bahwa sebuah website akan menerima permintaan. Kita harus mengukur hasil nyata, bukan menganggap kombinasi library tertentu akan menembus semua sistem deteksi.

3. Uji kompetitif yang lebih keras
Sebelum mengembangkan semua modul, kita perlu membuat laboratorium pengujian. Setiap skenario mempunyai ground truth, kondisi awal, kriteria sukses, batas sumber daya, dan hasil yang dapat diulang.

A
HTTP biasa

HTML, redirect, gzip/Brotli, koneksi lambat, dan respons besar.

B
JavaScript

Konten yang baru tersedia setelah hydration, interaksi, atau pemuatan API.

C
Sesi dan autentikasi

Login sah, token kedaluwarsa, cookie yang berubah, dan sesi yang dipulihkan.

D
Rate limiting

HTTP 429, Retry-After, backoff, dan pembatasan concurrency.

E
Challenge terkontrol

Fixture lokal untuk menguji deteksi challenge, alur verifikasi, dan penghentian aman.

F
Unduhan sulit

File tanpa ekstensi, MIME keliru, transfer terputus, server tanpa dukungan resume.

G
Kegagalan runtime

Browser crash, timeout, DNS/TLS failure, proses mati, dan pemulihan job.

H
Skala dan efisiensi

Banyak URL, domain berbeda, duplikasi, batas memori, throughput, dan p95 latency.

Setiap pengujian perlu membandingkan:

Keberhasilan akuisisi terverifikasi, bukan sekadar status HTTP 200.

Ketepatan diagnosis penyebab kegagalan.

Keberhasilan pemulihan sesi atau job jika pemulihan memang memungkinkan.

Latensi median dan p95, throughput, memori puncak, dan konsumsi CPU.

Integritas artifact dan kemampuan melanjutkan pekerjaan setelah proses berhenti.

Stabilitas hasil pada beberapa pengulangan.

Target pengujian challenge harus mencakup lingkungan yang kita kendalikan dan akses yang memang diizinkan. Kita tidak boleh mengklaim bisa menyelesaikan setiap proteksi website modern; beberapa challenge membutuhkan autentikasi, verifikasi manusia, atau izin akses.

4. Jangan membangun ratusan modul sekaligus
Urutan implementasi yang lebih kuat adalah:

Competitor reconnaissance: inventaris kode sumber Botasaurus, dependensi langsung, dependensi transitif, adapter, serta fitur yang benar-benar diuji. Angka lebih dari 120 modul perlu dihitung dengan definisi yang konsisten.

Access laboratory: bangun fixture lokal yang meniru skenario di atas dan tentukan metrik keberhasilan.

Transport prototype: implementasikan kontrak adapter dan uji beberapa transport secara berdampingan.

Adaptive planner: gunakan hasil diagnosis untuk memilih strategi berikutnya.

Browser dan session runtime: tambahkan observasi jaringan, lifecycle browser, dan pemulihan sesi.

Durable artifact pipeline: pastikan akuisisi dan ekstraksi dapat gagal secara terpisah.

Competitive benchmark: jalankan kedua platform dengan kondisi yang sama, lalu prioritaskan kelemahan yang terukur.

Tujuan akhirnya bukan memiliki modul terbanyak. Tujuannya adalah memiliki lebih banyak skenario yang berhasil, diagnosis yang lebih akurat, pemulihan yang lebih andal, dan biaya eksekusi yang lebih rendah dibandingkan baseline Botasaurus.

5. Saya perlu menetapkan arah pengembangan berikutnya
Kita sudah memiliki beberapa versi blueprint konseptual. Mengulang blueprint lain tanpa melihat lingkungan dan kode Botasaurus yang sebenarnya tidak akan membuktikan bahwa desain baru lebih kuat.

Tentukan langkah berikutnya
Pilih arah yang ingin dijadikan pekerjaan teknis utama. Kita bisa menggabungkan hasilnya secara bertahap.

1. Sasaran perbandingan


Audit source code dan seluruh modul Botasaurus

Menguji website modern dengan deteksi bot yang kuat

Keduanya: audit Botasaurus sekaligus benchmark akses modern
2. Lingkungan pengembangan


Termux Android, tanpa root dan tanpa PC

Linux/Ubuntu dengan Python virtual environment

Arsitektur lintas platform, dengan Termux sebagai target penting
3. Prioritas implementasi awal


Diagnosis akses, strategi adaptif, dan pemulihan sesi

Ekosistem transport HTTP dan browser yang lengkap

Seluruh mesin: discovery, akuisisi, artifact, plugin, dan benchmark
Saran saya: pilih keduanya. Kita perlu mengetahui apa yang sudah dimiliki Botasaurus dan sekaligus menguji celahnya. Tanpa dua hal tersebut, kita hanya menambah kompleksitas berdasarkan dugaan, bukan membangun keunggulan yang terukur.

Lanjutkan rancangan Universal Web Acquisition Engine dengan sasaran: audit Botasaurus sekaligus benchmark akses website modern. Lingkungan: Termux Android tanpa root dan tanpa PC. Prioritas: diagnosis akses, strategi adaptif, dan pemulihan sesi. Jangan ulangi blueprint generik. Berikan rencana teknis yang dapat dieksekusi, audit berbasis bukti, kontrak modul, urutan implementasi, serta kriteria benchmark yang dapat diverifikasi. Jangan klaim mengungguli Botasaurus sebelum ada hasil pengujian.
Universal Web Acquisition Engine — Rencana Implementasi Kompetitif v1
Target: membangun mesin akuisisi web yang bisa diuji secara objektif terhadap Botasaurus, dengan Termux Android tanpa root, tanpa PC, dan prioritas pada diagnosis akses, strategi adaptif, serta pemulihan sesi.

Kita tidak akan langsung membuat puluhan direktori dan ratusan modul. Langkah pertama adalah menghasilkan dua artefak yang menjadi dasar seluruh implementasi:

Botasaurus Evidence Baseline — inventaris source code, dependensi, kapabilitas, dan perilaku yang benar-benar dapat diverifikasi.

Modern Access Benchmark — laboratorium yang menguji kapan strategi HTTP, transport alternatif, sesi, atau browser berhasil maupun gagal.

Pemisahan ini penting karena dokumentasi Botasaurus sudah menunjukkan adanya kapabilitas seperti eksekusi paralel, cache, retry, dan penggunaan browser maupun request. Karena itu, implementasi kita harus menguji kemampuan yang benar-benar menjadi pembeda, bukan sekadar menambahkan fitur yang sudah tersedia. 

GitHub

Ada satu batas teknis yang harus kita perhitungkan sejak awal: Termux adalah lingkungan Android, bukan Linux desktop biasa. Playwright mempunyai dukungan eksperimental untuk mengotomatisasi Chrome Android melalui ADB, tetapi itu berbeda dari menjalankan browser desktop yang dibundel dengan Playwright Python. 

Playwright
 Begitu pula, curl_cffi memiliki kemampuan fingerprint TLS dan HTTP/2/HTTP/3 tertentu, tetapi dokumentasinya sendiri tidak menjamin bahwa sebuah situs akan menerima permintaan. 

curl_cffi documentation
+1

1. Definisi hasil akhir yang akan kita bangun
Access Intelligence Controller
Menganalisis bukti, menentukan strategi, dan memutuskan langkah berikutnya

HTTP transports

HTTPX, Requests, aiohttp, urllib3, curl_cffi jika kompatibel

Browser adapter

Chrome Android melalui ADB atau browser runtime lain yang telah diverifikasi

Session recovery

Autentikasi, kedaluwarsa, pemulihan yang sah, dan verifikasi pengguna

Evidence & evaluation

Hasil terukur, riwayat strategi, klasifikasi kegagalan, dan regresi

Verified Acquisition Result
Konten tervalidasi, artifact utuh, status akses jelas, dan bukti yang dapat diaudit

Sistem tidak boleh menyimpulkan keberhasilan hanya dari HTTP 200. Respons bisa berupa halaman login, challenge, halaman kosong, atau konten yang tidak sesuai target.

2. Fase 0 — audit source code Botasaurus dari Termux
Kita mulai dari source code yang dapat diperiksa, bukan jumlah modul yang diklaim atau jumlah paket yang terpasang.

Repositori publik Botasaurus memuat beberapa direktori dan komponen terpisah, termasuk botasaurus, bota, botasaurus_api, botasaurus_server, dan komponen cache. Audit harus memeriksa struktur serta tanggung jawab komponen tersebut. 

GitHub

2.1 Siapkan lingkungan audit
Jalankan di Termux. Perintah ini tidak memerlukan root dan tidak menginstal seluruh dependensi Botasaurus.


pkg update
pkg install -y git python ripgrep

mkdir -p ~/universal-web-acquisition
cd ~/universal-web-acquisition

git clone https://github.com/omkarcloud/botasaurus.git vendor-botasaurus

Jika repositori sudah pernah di-clone, jangan jalankan git clone lagi. Masuk ke direktori yang ada dan periksa statusnya terlebih dahulu.


cd ~/universal-web-acquisition/vendor-botasaurus

git rev-parse HEAD
git status --short
git log -1 --format='%H%n%cI%n%s'

git ls-files > ../botasaurus-tracked-files.txt
git ls-files '*.py' > ../botasaurus-python-files.txt

printf '\nTracked files: '
wc -l < ../botasaurus-tracked-files.txt

printf 'Tracked Python files: '
wc -l < ../botasaurus-python-files.txt

printf '\nTop-level structure:\n'
find . -maxdepth 2 -type f | sort | head -250

Simpan commit SHA yang dihasilkan. Semua hasil audit berikutnya harus merujuk SHA tersebut agar perubahan source code di masa depan tidak mengubah baseline secara diam-diam.

2.2 Hitung modul secara benar
Jangan mencampur empat ukuran berbeda:

Ukuran

Definisi

File Python

Jumlah file .py yang terlacak

Modul import

Modul Python yang bisa diimpor berdasarkan struktur package

Paket langsung

Dependensi yang dinyatakan oleh proyek

Paket transitif

Dependensi yang ditarik oleh dependensi lain

Angka lebih dari 120 modul di virtual environment belum membuktikan bahwa Botasaurus mempunyai 120 modul miliknya sendiri. Sebaliknya, jumlah file Python yang sedikit juga tidak berarti kemampuan framework sedikit.

Buat inventaris awal:


cd ~/universal-web-acquisition/vendor-botasaurus

printf '%s\n' '=== Package/build metadata ==='
rg -n 'install_requires|extras_require|dependencies|optional-dependencies|entry_points|console_scripts' \
  setup.py setup.cfg pyproject.toml setup.* 2>/dev/null

printf '%s\n' '=== HTTP, retry, cache, session ==='
rg -n -i 'httpx|requests|aiohttp|urllib3|curl_cffi|retry|backoff|cache|cookie|session|timeout|proxy' \
  --glob '*.py' --glob '*.toml' --glob '*.cfg' --glob '*.txt' .

printf '%s\n' '=== Browser, challenge, network ==='
rg -n -i 'playwright|selenium|chrome|chromium|cloudflare|captcha|fingerprint|webdriver|network|download' \
  --glob '*.py' --glob '*.js' --glob '*.md' .

Jangan langsung menganggap semua hasil pencarian merupakan fitur aktif. Setiap temuan harus diberi klasifikasi:

Implemented: kode implementasinya ditemukan.

Tested: terdapat tes yang menguji perilaku tersebut.

Documented: hanya dinyatakan dalam dokumentasi.

Verified: perilaku berhasil direproduksi di lingkungan pengujian.

Unknown: belum ada bukti cukup.

Contoh: dokumentasi Botasaurus menerangkan penggunaan request untuk jenis challenge tertentu dan browser untuk challenge yang membutuhkan eksekusi JavaScript. Itu merupakan petunjuk audit yang berguna, tetapi belum membuktikan tingkat keberhasilan pada setiap situs atau pada Termux. 

GitHub

2.3 Hasil audit yang wajib dihasilkan
Struktur hasil audit awal:

docs/
├── audit/
│   ├── environment.md
│   ├── source-inventory.json
│   ├── dependency-inventory.json
│   ├── capability-evidence.csv
│   └── botasaurus-limitations.md
├── benchmark/
│   ├── scenario-catalog.json
│   ├── benchmark-protocol.md
│   └── baseline-results.json
└── architecture/
    ├── access-state-machine.md
    └── adapter-contracts.md
botasaurus-limitations.md tidak boleh menjadi daftar asumsi negatif tentang kompetitor. Isinya harus berupa kelemahan yang benar-benar berhasil direproduksi, batasan platform yang terkonfirmasi, atau celah pengujian yang masih belum terjawab.

3. Fase 1 — verifikasi kompatibilitas transport di Android
Kita tidak akan menginstal semua transport sekaligus. Kita akan menguji setiap kandidat secara terisolasi agar satu paket native yang tidak kompatibel tidak merusak seluruh lingkungan.

3.1 Buat lingkungan Python terpisah

cd ~/universal-web-acquisition

python -VV
python -m pip --version

mkdir -p .venvs

python -m venv .venvs/audit
. .venvs/audit/bin/activate

python -m pip install --upgrade pip
python -m pip install httpx requests aiohttp urllib3 beautifulsoup4 lxml
python -m pip check

Jika suatu paket gagal dipasang atau gagal diimpor, catat kegagalannya sebagai hasil audit platform; jangan langsung mengganti paket atau menyembunyikan error.

Uji import dan versi:


python - <<'PY'
import importlib
import importlib.metadata as md

packages = [
    ("httpx", "httpx"),
    ("requests", "requests"),
    ("aiohttp", "aiohttp"),
    ("urllib3", "urllib3"),
    ("beautifulsoup4", "bs4"),
    ("lxml", "lxml"),
    ("curl-cffi", "curl_cffi"),
    ("playwright", "playwright"),
]

for distribution, module in packages:
    try:
        imported = importlib.import_module(module)
        try:
            version = md.version(distribution)
        except md.PackageNotFoundError:
            version = "distribution metadata unavailable"
        print(f"OK      {distribution:16} {version:30} {getattr(imported, '__file__', '')}")
    except Exception as exc:
        print(f"FAILED  {distribution:16} {type(exc).__name__}: {exc}")
PY

Hasil FAILED di sini belum tentu berarti paket tidak mendukung Android secara keseluruhan; penyebabnya bisa berupa wheel yang tidak tersedia, dependensi native, atau lingkungan yang belum memenuhi persyaratan.

3.2 Matriks transport yang harus diukur
Kandidat

Peran dalam arsitektur

Pemeriksaan utama

httpx

Transport sinkron dan asinkron

Timeout, connection pooling, streaming, proxy, HTTP/2

requests

Transport sinkron kompatibilitas luas

Sesi, redirect, cookie, streaming

aiohttp

Transport asinkron

Concurrency, timeout, streaming, koneksi

urllib3

Lapisan HTTP tingkat lebih rendah

Pooling, retry, koneksi, TLS

curl_cffi

Transport opsional dengan kapabilitas fingerprint tertentu

Wheel Android, native compatibility, protokol, session

Browser adapter

Render JavaScript dan interaksi

Runtime tersedia, lifecycle, DOM, network events

curl_cffi tidak boleh menjadi dependensi wajib sebelum pemasangan, import, dan permintaan HTTPS berhasil diuji pada perangkat yang dituju. Dokumentasinya menjelaskan dukungan fingerprint dan protokol, tetapi tidak menjamin kompatibilitas setiap platform atau penerimaan oleh setiap target. 

GitHub
+1

Demikian juga, jangan memasukkan Playwright Python desktop ke jalur utama Termux sebelum ada bukti runtime browser yang dapat berjalan. Untuk Chrome Android, jalur eksperimental Playwright melalui ADB adalah opsi terpisah yang harus divalidasi sendiri. 

Playwright

4. Fase 2 — kontrak inti yang harus stabil sebelum implementasi besar
Keunggulan mesin adaptif bergantung pada kontrak yang jelas. Adapter transport tidak boleh menentukan sendiri apakah sebuah halaman merupakan hasil sukses; keputusan itu merupakan tanggung jawab lapisan diagnosis dan validasi.

4.1 Access assessment

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AccessState(StrEnum):
    ACCESS_GRANTED = "access_granted"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    CHALLENGE_PRESENT = "challenge_present"
    JAVASCRIPT_REQUIRED = "javascript_required"
    CONTENT_INVALID = "content_invalid"
    NETWORK_FAILURE = "network_failure"
    ACCESS_DENIED = "access_denied"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Evidence:
    source: str
    signal: str
    observed: str
    confidence: float
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AccessAssessment:
    url: str
    state: AccessState
    confidence: float
    evidence: tuple[Evidence, ...]
    recommended_action: str
    retry_after_seconds: float | None = None

Ini adalah kontrak awal, bukan classifier lengkap. Implementasinya harus menghindari kesimpulan yang terlalu yakin berdasarkan satu sinyal saja.

Contohnya:

HTTP 200 + halaman login yang tidak diharapkan → AUTH_REQUIRED atau CONTENT_INVALID, bergantung pada target.

HTTP 429 → RATE_LIMITED, kemudian hormati Retry-After jika valid.

Timeout DNS → NETWORK_FAILURE, bukan CHALLENGE_PRESENT.

HTML kosong atau struktur target hilang → perlu validasi tambahan, bukan otomatis menganggap website memblokir scraper.

CAPTCHA atau challenge yang terdeteksi → simpan bukti, ikuti alur verifikasi yang diizinkan, atau hentikan pekerjaan.

4.2 Transport adapter

from dataclasses import dataclass
from typing import AsyncIterator, Protocol


@dataclass(frozen=True)
class TransportCapabilities:
    sync: bool
    async_: bool
    streaming: bool
    session_cookies: bool
    proxy: bool
    http2: bool
    http3: bool
    browser_runtime: bool = False


@dataclass(frozen=True)
class RequestSpec:
    url: str
    method: str = "GET"
    headers: dict[str, str] | None = None
    timeout_seconds: float = 20.0


@dataclass(frozen=True)
class ResponseMetadata:
    requested_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    elapsed_seconds: float
    transport_name: str


class TransportAdapter(Protocol):
    @property
    def capabilities(self) -> TransportCapabilities: ...

    async def request(self, spec: RequestSpec) -> ResponseMetadata: ...

    async def stream(
        self, spec: RequestSpec
    ) -> AsyncIterator[bytes]: ...

Kontrak tersebut memisahkan metadata respons dari streaming body agar artifact berukuran besar tidak perlu dimuat seluruhnya ke RAM. Implementasi sinkron dapat dibungkus dengan executor atau diberikan adapter sinkron terpisah; jangan berpura-pura bahwa setiap transport mendukung operasi asinkron.

Aturan wajib:

Kapabilitas harus menyatakan dukungan nyata, bukan nilai yang diasumsikan.

Adapter harus mempertahankan error asli melalui error type yang terstruktur.

Timeout koneksi dan timeout pembacaan harus dapat dibedakan jika transport mendukungnya.

Kredensial, cookie, dan token tidak boleh masuk ke log mentah.

Pergantian transport harus terjadi karena keputusan planner, bukan karena setiap error langsung mencoba seluruh library.

4.3 Session recovery contract
Sesi perlu memiliki identitas, status, dan siklus hidup. Jangan menyamakan penyimpanan cookie dengan pemulihan autentikasi yang berhasil.

Status minimum:

NEW
  ↓
ACTIVE
  ├──→ EXPIRING
  │      ↓
  │   REAUTH_REQUIRED
  │      ↓
  │   RECOVERY_PENDING
  │      ↓
  │   ACTIVE / FAILED
  ├──→ INVALID
  └──→ CLOSED
Setiap recovery attempt harus merekam:

jenis kegagalan yang memicu recovery;

ID sesi, tanpa mencatat rahasia sesi;

tindakan yang dilakukan;

hasil autentikasi atau verifikasi;

apakah konten target benar-benar dapat diakses setelah pemulihan;

jumlah percobaan dan alasan berhenti.

Tidak boleh ada loop login atau retry tanpa batas. CAPTCHA yang memerlukan verifikasi manusia harus mempunyai status WAITING_FOR_USER atau status setara, bukan diubah menjadi keberhasilan palsu.

5. Fase 3 — adaptive strategy planner
Planner adalah subsistem utama yang membedakan mesin adaptif dari sekadar kumpulan transport.

Input-nya bukan hanya URL, melainkan:

AccessAssessment;

hasil strategi sebelumnya;

kapabilitas transport yang tersedia;

status sesi;

anggaran waktu dan sumber daya;

aturan akses dan batas percobaan.

Output-nya berupa keputusan yang dapat dijelaskan.

Bukti

Tindakan berikutnya

Halaman publik berhasil dan konten valid

Simpan hasil; jangan mencoba strategi lain

HTML belum berisi konten yang ditargetkan

Periksa apakah perlu JavaScript atau apakah selector/target salah

Sesi telah kedaluwarsa

Gunakan jalur autentikasi resmi atau minta intervensi pengguna

HTTP 429

Hormati Retry-After, turunkan concurrency, dan hindari retry agresif

Kegagalan DNS/TLS/koneksi

Diagnosis jaringan dan transport sebelum menyimpulkan pemblokiran

Challenge terdeteksi

Klasifikasikan bukti dan gunakan alur verifikasi yang diizinkan

Akses ditolak secara eksplisit

Berhenti atau gunakan jalur akses resmi

Strategi alternatif gagal berulang

Catat kegagalan terminal beserta bukti; jangan terus memutar transport

Planner versi pertama harus berupa aturan deterministik yang dapat diuji. Kita tidak membutuhkan model machine learning sebelum memiliki corpus kegagalan dan label yang dapat dipercaya.

Ukuran kualitas diagnosis
Classifier diuji menggunakan fixture yang label sebenarnya sudah diketahui.

Precision dan recall per kelas.

Confusion matrix.

False positive: halaman normal diklasifikasikan sebagai challenge.

False negative: challenge tidak terdeteksi.

Persentase UNKNOWN, yang harus tetap diperbolehkan ketika bukti tidak cukup.

Akurasi pemilihan tindakan berikutnya.

Jangan hanya mengukur accuracy keseluruhan. Jika mayoritas fixture merupakan halaman normal, accuracy tinggi dapat menutupi kegagalan mengenali kondisi yang jarang tetapi penting.

6. Fase 4 — bangun benchmark yang dapat direproduksi
Kita perlu membandingkan Botasaurus dan Universal Web Acquisition Engine pada target yang sama, perangkat yang sama, kondisi jaringan yang sama, dan definisi keberhasilan yang sama.

Untuk target publik yang memiliki proteksi kuat, lakukan pengujian hanya pada akses yang diizinkan. Jangan menganggap perubahan fingerprint, proxy, atau browser akan selalu menyelesaikan challenge.

6.1 Skenario wajib
ID

Skenario

Ground truth

A01

HTML publik

Konten dan marker target ditemukan

A02

Redirect berantai

URL final dan konten sesuai target

A03

JavaScript hydration

Elemen target tersedia setelah render

A04

Autentikasi

Sesi sah dapat mengakses resource yang ditentukan

A05

Sesi kedaluwarsa

Sistem mengenali expiry dan masuk ke recovery

A06

HTTP 429

Retry sesuai kebijakan dan tidak mengabaikan Retry-After

A07

Challenge simulasi lokal

Klasifikasi dan tindakan cocok dengan ground truth

A08

DNS/TLS/timeout

Penyebab kegagalan tidak salah diklasifikasikan

A09

Unduhan terputus

Artifact dapat dilanjutkan jika server mendukung resume

A10

Proses mati

Job yang dapat dipulihkan kembali tanpa menduplikasi hasil

A11

HTML tidak valid

Sistem tidak melaporkan sukses hanya karena status 200

A12

Transport tidak kompatibel

Fallback atau kegagalan terstruktur sesuai kebijakan

Buat server fixture lokal untuk skenario yang dapat dikendalikan. Dengan demikian, kita bisa menguji 429, expiry, redirect, HTML invalid, dan koneksi terputus tanpa bergantung pada perilaku website eksternal yang bisa berubah sewaktu-waktu.

6.2 Format hasil benchmark
Simpan satu record JSON untuk setiap percobaan, bukan hanya ringkasan akhir.


{
  "schema_version": 1,
  "scenario_id": "A03",
  "run_id": "generated-run-id",
  "engine": "uwae",
  "engine_version": "0.1.0",
  "source_commit": "git-commit-sha",
  "environment": {
    "platform": "android-termux",
    "python_version": "record-at-runtime",
    "transport": "httpx"
  },
  "input": {
    "target_id": "local-fixture-js-01"
  },
  "result": {
    "success": false,
    "expected_state": "access_granted",
    "observed_state": "javascript_required",
    "content_valid": false,
    "artifact_integrity": null
  },
  "performance": {
    "elapsed_ms": null,
    "peak_memory_bytes": null,
    "attempt_count": 1
  },
  "evidence": [],
  "failure_reason": "browser_adapter_not_available"
}

Nilai null berarti belum diukur atau tidak berlaku. Jangan mengisi metrik dengan angka perkiraan. Dalam implementasi nyata, run_id, versi Python, commit, dan waktu eksekusi harus dihasilkan otomatis.

6.3 Kriteria kelulusan
Sebelum benchmark kompetitif, tetapkan ambang berikut sebagai kriteria engineering awal, bukan hasil yang sudah tercapai.

100% fixture deterministik memiliki expected outcome yang eksplisit.

100% hasil memiliki commit, versi runtime, dan scenario ID.

Tidak ada keberhasilan akuisisi tanpa validasi konten.

Tidak ada retry tanpa batas.

Tidak ada kredensial mentah pada log dan artifact metadata.

Semua kegagalan terminal memiliki kategori dan bukti.

Minimal 30 pengulangan untuk skenario benchmark utama sebelum membandingkan performa.

Laporkan median, p95, rentang hasil, serta jumlah keberhasilan dan kegagalan.

Bandingkan performa hanya pada fitur yang tersedia dan dapat dijalankan pada kedua sistem.

Ambang ini adalah gerbang kualitas internal. Untuk klaim keunggulan, kita tetap memerlukan hasil eksperimen yang mendukungnya.

7. Urutan implementasi untuk AI coding agent
Jangan meminta agent membangun semua komponen sekaligus. Gunakan urutan ini agar setiap fase meninggalkan hasil yang bisa diperiksa.

Audit dan baseline. Clone serta pin commit Botasaurus, hitung source dan dependensi, catat dukungan platform, dan buat laporan evidence. Belum perlu membangun scraper baru.

Fixture server dan benchmark schema. Bangun endpoint pengujian lokal, ground truth, pencatat hasil, dan runner. Pastikan pengujian deterministik berjalan sebelum menambah transport.

Transport registry. Implementasikan satu adapter HTTP yang kompatibel terlebih dahulu, kemudian tambah adapter lain satu per satu berdasarkan hasil uji Termux.

Access classifier. Implementasikan state dan evidence model; tambahkan unit test untuk seluruh kelas serta false positive dan false negative.

Strategy planner. Hubungkan classifier dengan keputusan deterministik, anggaran retry, kebijakan akses, dan hasil strategi sebelumnya.

Session recovery. Tambahkan penyimpanan sesi yang aman, expiry detection, autentikasi sah, recovery state machine, dan verifikasi hasil pascarecovery.

Browser capability spike. Verifikasi apakah jalur Chrome Android/ADB benar-benar dapat menjalankan skenario JavaScript target. Jika tidak, laporkan batasan dan jangan membuat browser adapter palsu.

Differential benchmark. Jalankan Botasaurus dan mesin baru pada skenario yang sama, ekspor hasil mentah, analisis selisih, dan pilih kelemahan terbesar untuk iterasi berikutnya.

8. Instruksi implementasi siap diberikan kepada Claude Code atau Hermes
9. Gerbang keputusan sebelum kita mengklaim ada kemajuan kompetitif
Setelah fase pertama selesai, hasilnya harus menjawab pertanyaan nyata:

Berapa banyak modul Botasaurus yang merupakan kode proyek sendiri, dan berapa banyak dependensi pihak ketiga?

Fitur apa yang benar-benar berfungsi pada lingkungan yang diuji?

Apakah browser automation yang dibutuhkan tersedia di perangkat Android tersebut?

Kapan HTTP-only lebih baik daripada membuka browser?

Apakah diagnosis dapat membedakan challenge, autentikasi, rate limit, dan gangguan jaringan?

Apakah pemulihan sesi berhasil pada fixture yang mendukungnya?

Di skenario mana mesin baru mengungguli baseline, sama, atau justru gagal?

Baru setelah itu kita memilih fitur berikutnya berdasarkan hasil pengujian. Untuk saat ini, belum ada bukti bahwa Universal Web Acquisition Engine lebih unggul dari Botasaurus. Rencana ini dirancang untuk menghasilkan bukti yang diperlukan agar kita dapat membangunnya secara sistematis, khususnya pada diagnosis akses, strategi adaptif, dan pemulihan sesi.

Ini masih kurang
Saya menangkap masalahnya: rancangan sebelumnya masih berupa arsitektur, beberapa kontrak Python, dan daftar fase. Itu belum menjadi spesifikasi engineering yang cukup ketat untuk membangun pesaing Botasaurus.

Kekurangan terbesarnya adalah kita belum menetapkan bagaimana mesin membuat keputusan dari bukti nyata, bagaimana strategi dibandingkan, bagaimana kegagalan didiagnosis sampai ke akar masalah, bagaimana sesi dan job dipulihkan, serta bagaimana kita membuktikan bahwa pendekatan baru lebih baik.

Kita perlu satu tingkat lebih dalam: spesifikasi perilaku, kontrak antarsubsistem, model data, algoritme keputusan, eksperimen kompetitif, gerbang penerimaan, dan perintah eksekusi yang tidak mengasumsikan kemampuan Android yang belum terverifikasi.

Universal Web Acquisition Engine — Engineering Specification v2
1. Prinsip desain: bukan scraper dengan banyak adapter
Mesin harus menjadi sistem yang melakukan siklus berikut untuk setiap pekerjaan:

1
Observe
Kumpulkan respons, metadata, status sesi, dan sinyal runtime.

2
Diagnose
Klasifikasikan kondisi akses beserta bukti dan tingkat keyakinan.

3
Decide
Pilih tindakan berikutnya berdasarkan kebijakan, kapabilitas, dan biaya.

4
Execute
Jalankan strategi melalui adapter yang telah diverifikasi.

5
Validate
Pastikan konten benar-benar sesuai dengan tujuan akuisisi.

6
Learn from evidence
Simpan hasil untuk evaluasi kebijakan dan regresi.

Siklus berulang hanya jika tindakan berikutnya masuk akal, diizinkan, dan masih berada dalam anggaran pekerjaan.

Perbedaan pentingnya: hasil satu percobaan menjadi input bagi keputusan berikutnya. Sistem tidak boleh sekadar menjalankan daftar fallback tetap seperti requests → httpx → curl_cffi → browser, karena semua itu bisa gagal akibat penyebab yang sama.

2. Audit Botasaurus berdasarkan kemampuan yang benar-benar dimilikinya
Audit harus dimulai dengan asumsi bahwa Botasaurus sudah merupakan kompetitor yang matang, bukan scraper sederhana.

Dokumentasi publiknya menjelaskan beberapa kemampuan yang relevan:

@request dan @browser, termasuk konfigurasi retry, cache, paralelisme, serta pengelolaan error.

Request berbasis hrequests melalui botasaurus-requests, dengan karakteristik koneksi yang ditujukan menyerupai browser.

Browser dengan konfigurasi profil, proxy, penggunaan ulang driver, dan alur interaksi challenge tertentu.

Penggunaan request dari browser untuk mengambil konten dengan lebih efisien setelah sesi browser dibuka. 

GitHub
+1

Ini merupakan kapabilitas yang terdokumentasi, bukan hasil benchmark independen. Artinya, mesin baru tidak bisa mengklaim unggul hanya karena memiliki request, browser, cache, retry, dan proxy.

Matriks audit kompetitif
Area

Apa yang diperiksa di Botasaurus

Apa yang harus diuji pada mesin baru

HTTP request

Implementasi request, stack HTTP, cookie, redirect

Keberhasilan dan waktu respons pada fixture identik

Browser

Driver, lifecycle, profil, crash handling

Ketersediaan runtime Android dan pemulihan browser

Challenge

Detektor, kondisi aktivasi, alur pengguna

Ketepatan klasifikasi, false positive, dan hasil verifikasi

Session

Penyimpanan cookie, reuse, autentikasi

Expiry detection, isolasi sesi, dan recovery

Retry

Kondisi retry, jeda, exception

Retry berdasarkan kelas kegagalan dan anggaran

Cache

Cache key, invalidasi, hasil yang disimpan

Validitas cache, deduplikasi, dan penghindaran data basi

Paralelisme

Model concurrency, batas browser/request

Throughput dan stabilitas dalam batas memori Android

Unduhan

Streaming, penyimpanan, integritas

File parsial, resume, checksum, dan pemulihan

Diagnosis

Log dan informasi error

Bukti terstruktur dan penyebab kegagalan yang dapat diuji

Portabilitas

Dependensi, runtime, instalasi

Keberhasilan instalasi serta operasi pada Termux

Satu hal yang sangat penting: dokumentasi Botasaurus menunjukkan bahwa request dan browser mempunyai fungsi berbeda ketika sebuah challenge memerlukan eksekusi JavaScript atau interaksi tambahan. 

GitHub
 Karena itu, pengujian harus menentukan kapan masing-masing jalur bekerja, kapan gagal, dan apakah kegagalannya dapat didiagnosis, bukan mengasumsikan bahwa satu adapter lebih unggul untuk semua situs.

3. Definisi algoritme diagnosis akses
Kita memerlukan classifier yang mengubah observasi menjadi keadaan terstruktur. Jangan mulai dari machine learning; mulailah dari aturan deterministik yang hasilnya dapat diverifikasi.

3.1 Urutan evaluasi

def classify_access(observation):
    """
    Pseudocode kontrak.
    Setiap helper harus mengembalikan bukti yang dapat diaudit.
    """

    if observation.network_error:
        return classify_network_failure(observation)

    if observation.explicit_rate_limit:
        return assessment(
            state="rate_limited",
            action="respect_retry_after",
        )

    if observation.explicit_auth_required:
        return assessment(
            state="auth_required",
            action="reauthenticate_or_request_user",
        )

    if observation.explicit_access_denial:
        return assessment(
            state="access_denied",
            action="stop_or_use_authorized_access",
        )

    if observation.challenge_evidence:
        return assessment(
            state="challenge_present",
            action="authorized_challenge_workflow",
        )

    if observation.target_content_valid:
        return assessment(
            state="access_granted",
            action="persist_result",
        )

    if observation.javascript_evidence:
        return assessment(
            state="javascript_required",
            action="check_browser_capability",
        )

    if observation.response_received:
        return assessment(
            state="content_invalid",
            action="inspect_content_and_target",
        )

    return assessment(
        state="unknown",
        action="collect_more_evidence",
    )

Ini pseudocode untuk menjelaskan urutan keputusan, bukan kode siap produksi. Implementasi sebenarnya harus memastikan bahwa sinyal tidak tumpang tindih secara keliru.

Contohnya, status HTTP 403 saja tidak cukup untuk menyimpulkan CAPTCHA atau deteksi bot. Status tersebut bisa berarti akses ditolak karena izin, aturan aplikasi, autentikasi, atau kebijakan server. Demikian pula, halaman tanpa elemen target tidak otomatis berarti JavaScript diperlukan.

3.2 Skema bukti
Setiap keputusan classifier harus menyimpan informasi seperti berikut:


{
  "observation_id": "obs-000123",
  "target_id": "fixture-auth-01",
  "transport": "httpx",
  "response": {
    "status": 200,
    "final_url": "https://fixture.example.test/login",
    "content_type": "text/html"
  },
  "signals": [
    {
      "name": "login_form_detected",
      "value": true,
      "source": "html_validator"
    },
    {
      "name": "expected_marker_found",
      "value": false,
      "source": "content_validator"
    }
  ],
  "assessment": {
    "state": "auth_required",
    "confidence": 0.97,
    "reason_codes": [
      "LOGIN_FORM_PRESENT",
      "TARGET_MARKER_MISSING"
    ]
  },
  "policy": {
    "action": "reauthenticate_or_request_user",
    "attempt": 1
  }
}

Angka confidence di atas hanya ilustrasi format, bukan hasil pengukuran. Dalam implementasi nyata, confidence harus dikalibrasi terhadap corpus berlabel. Jika belum ada dasar statistik untuk memberi probabilitas, gunakan kategori keyakinan dan reason code terlebih dahulu.

3.3 Klasifikasi harus dapat diaudit
Setiap reason code mempunyai definisi, sumber bukti, dan tes.

Reason code

Bukti minimum

Tes wajib

HTTP_RATE_LIMIT

Status 429 atau sinyal rate limit yang tervalidasi

429 dengan dan tanpa Retry-After

LOGIN_FORM_PRESENT

Marker formulir login yang sesuai aturan target

Halaman login dan halaman normal

TARGET_MARKER_MISSING

Validasi konten tidak menemukan marker wajib

HTML normal, kosong, dan tidak lengkap

DNS_RESOLUTION_FAILED

Error resolver yang dapat dikenali

Host fixture yang tidak dapat di-resolve

TLS_HANDSHAKE_FAILED

Error TLS yang teridentifikasi

Sertifikat tidak valid pada fixture

CHALLENGE_SIGNATURE_MATCH

Marker challenge yang terverifikasi

Challenge fixture dan halaman normal yang mirip

BROWSER_RUNTIME_UNAVAILABLE

Runtime browser gagal ditemukan atau dijalankan

Browser tidak terpasang dan browser yang tersedia

Dengan pendekatan ini, kita dapat memperbaiki satu jenis kesalahan diagnosis tanpa menulis ulang seluruh sistem.

4. Planner: memilih strategi berdasarkan biaya dan bukti
Planner harus mempertimbangkan bukan hanya kemungkinan berhasil, tetapi juga biaya, risiko kegagalan, status sesi, dan apakah tindakan berikutnya diizinkan.

4.1 Model keputusan
Untuk setiap kandidat strategi 
s
s, simpan:

Kapabilitas yang dibutuhkan.

Bukti keberhasilan sebelumnya pada kelas skenario yang sama.

Latensi dan penggunaan sumber daya yang terukur.

Tingkat kegagalan.

Persyaratan autentikasi atau intervensi pengguna.

Batas retry dan kebijakan akses.

Skor awal dapat berupa:

score
⁡
(
s
)
=
w
p
P
s
−
w
t
T
s
−
w
m
M
s
−
w
f
F
s
score(s)=w 
p
​
 P 
s
​
 −w 
t
​
 T 
s
​
 −w 
m
​
 M 
s
​
 −w 
f
​
 F 
s
​
 
dengan:

P
s
P 
s
​
 : estimasi keberhasilan yang dikalibrasi dari benchmark.

T
s
T 
s
​
 : biaya latensi yang dinormalisasi.

M
s
M 
s
​
 : biaya memori.

F
s
F 
s
​
 : biaya kegagalan dan pemulihan.

w
p
,
w
t
,
w
m
,
w
f
w 
p
​
 ,w 
t
​
 ,w 
m
​
 ,w 
f
​
 : bobot konfigurasi yang ditetapkan dan diuji.

Rumus ini hanya alat pengambilan keputusan. Ia tidak akan menghasilkan strategi yang baik tanpa data yang representatif. Versi pertama sebaiknya memakai aturan deterministik, kemudian evaluasi apakah skor berbasis data benar-benar memperbaiki hasil.

4.2 Contoh keputusan yang diharapkan
HTTP berhasil dan konten valid

Simpan hasil. Jangan membuka browser hanya untuk mengulangi pekerjaan yang sudah selesai.

Sesi kedaluwarsa

Gunakan mekanisme autentikasi resmi atau minta pengguna memperbarui sesi. Validasi kembali konten setelah pemulihan.

Rate limit

Patuhi waktu tunggu server, turunkan concurrency bila diperlukan, dan hindari perpindahan adapter yang hanya mengulangi permintaan terlalu cepat.

Konten memerlukan JavaScript

Periksa apakah browser runtime yang sesuai tersedia. Jika tidak tersedia, hasilkan kegagalan yang menjelaskan kemampuan yang kurang.

Challenge atau penolakan akses

Gunakan alur akses yang diizinkan, verifikasi pengguna, atau hentikan pekerjaan. Jangan melaporkan akses berhasil tanpa bukti.

Planner juga harus mencegah siklus seperti ini:

HTTP gagal
  → transport lain gagal
  → browser gagal
  → kembali ke HTTP
  → ulangi tanpa batas
Gunakan attempt_history, visited_strategy_states, dan retry_budget. Jika tidak ada bukti baru yang dapat diperoleh dari percobaan berikutnya, planner harus berhenti.

5. Model penyimpanan dan pemulihan yang tahan kegagalan
Mesin yang bagus bukan hanya bisa memulai pekerjaan, tetapi juga bisa menjelaskan dan memulihkannya setelah Termux ditutup, proses mati, atau koneksi terputus.

5.1 Model data minimum
Gunakan SQLite sebagai penyimpanan job dan state awal. SQLite merupakan pilihan yang masuk akal untuk aplikasi CLI lokal, tetapi konfigurasi transaksi, WAL, dan perilaku saat proses berhenti tetap harus diuji pada filesystem Android yang digunakan.

Tabel minimum:

Tabel

Tanggung jawab

jobs

Input, status, kebijakan, waktu pembuatan

attempts

Strategi, transport, hasil, durasi, error

observations

Bukti diagnosis yang telah disanitasi

sessions

Referensi sesi, status, expiry, metadata aman

artifacts

Path, ukuran, hash, identifikasi format

job_events

Transisi state yang dapat diaudit

benchmark_runs

Versi engine, skenario, hasil, dan konfigurasi

Setiap job harus mempunyai ID yang stabil. Job yang diulang setelah crash tidak boleh menghasilkan artifact ganda tanpa alasan yang tercatat.

5.2 Pemulihan job
Alur pemulihan:

Baca job yang belum terminal.

Periksa apakah ada attempt yang statusnya masih berjalan ketika proses mati.

Tandai attempt tersebut sebagai INTERRUPTED, bukan SUCCESS.

Periksa artifact parsial dan checkpoint.

Validasi apakah server mendukung resume sebelum melanjutkan unduhan.

Lanjutkan atau mulai ulang sesuai bukti.

Validasi ukuran, hash, dan konten.

Catat transisi state dan alasan keputusan.

Untuk unduhan HTTP, jangan menganggap Range selalu didukung. Jika server tidak menyediakan validator atau tidak mendukung resume, strategi yang benar mungkin mengulang unduhan dari awal, bukan menggabungkan byte secara spekulatif.

5.3 Integritas artifact
Untuk setiap artifact, simpan:

URL sumber dan URL final.

Waktu akuisisi.

Status respons dan MIME type.

Ukuran aktual.

SHA-256.

Identifikasi format berdasarkan signature, bukan hanya ekstensi.

Status validasi dan ekstraksi.

Referensi job dan attempt asal.

Akuisisi, identifikasi format, dan ekstraksi harus merupakan operasi terpisah. Jika ekstraksi gagal, artifact asli tidak boleh otomatis dibuang.

6. Arsitektur proyek yang lebih konkret
Mulailah dengan modul yang mempunyai kontrak nyata dan dapat diuji, bukan struktur folder besar yang belum memiliki implementasi.

universal-web-acquisition/
├── pyproject.toml
├── README.md
├── src/
│   └── uwae/
│       ├── cli.py
│       ├── config.py
│       ├── domain/
│       │   ├── models.py
│       │   ├── states.py
│       │   └── errors.py
│       ├── access/
│       │   ├── evidence.py
│       │   ├── classifier.py
│       │   ├── planner.py
│       │   └── policy.py
│       ├── transports/
│       │   ├── contracts.py
│       │   ├── registry.py
│       │   └── httpx_adapter.py
│       ├── sessions/
│       │   ├── models.py
│       │   ├── store.py
│       │   └── recovery.py
│       ├── jobs/
│       │   ├── repository.py
│       │   ├── scheduler.py
│       │   └── recovery.py
│       ├── artifacts/
│       │   ├── streaming.py
│       │   ├── integrity.py
│       │   └── identification.py
│       ├── observability/
│       │   ├── events.py
│       │   └── metrics.py
│       └── benchmark/
│           ├── runner.py
│           ├── schema.py
│           └── reporting.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── regression/
├── docs/
│   ├── audit/
│   ├── architecture/
│   └── benchmark/
└── scripts/
    ├── audit-botasaurus.sh
    └── run-benchmarks.sh
Browser adapter, curl_cffi, discovery graph, marketplace plugin, dan extraction registry ditambahkan setelah core, kontrak, dan benchmark terbukti berfungsi. Itu bukan berarti fitur tersebut tidak penting; urutannya mencegah kita membangun integrasi yang belum dapat dijalankan atau diverifikasi.

7. Gerbang penerimaan engineering
Setiap fase harus lulus pengujian sebelum dilanjutkan.

Gerbang

Syarat lulus

G0 — Audit

Commit Botasaurus dipatok; inventaris source/dependensi dan bukti terdokumentasi

G1 — Fixtures

Setiap skenario mempunyai ground truth; hasil fixture deterministik

G2 — Transport

Adapter lulus tes timeout, redirect, error, dan cleanup

G3 — Diagnosis

Precision/recall dilaporkan per kelas; kesalahan klasifikasi dapat ditelusuri

G4 — Planner

Tidak ada retry tanpa batas atau transisi state yang tidak sah

G5 — Session

Expiry, recovery, dan hasil pascarecovery terverifikasi

G6 — Durability

Job dan artifact dapat dipulihkan setelah simulasi proses mati

G7 — Benchmark

Hasil mentah dan laporan perbandingan dapat direproduksi

Untuk benchmark, 30 pengulangan per skenario dapat menjadi penyaringan awal, tetapi belum cukup untuk semua klaim statistik. Skenario eksternal yang berubah-ubah membutuhkan lebih banyak pengulangan, pengendalian kondisi, dan pelaporan ketidakpastian.

Perbandingan harus melaporkan:

tingkat keberhasilan dengan definisi sukses yang identik;

precision dan recall diagnosis;

median serta p95 latency;

peak memory dan jumlah percobaan;

kegagalan instalasi atau runtime;

integritas artifact;

hasil setiap skenario, termasuk yang tidak didukung oleh salah satu engine.

Jika Botasaurus tidak dapat dijalankan pada Termux, kita tetap dapat menyelesaikan audit source dan benchmark fitur yang bisa diuji, tetapi tidak boleh menyebut hasil tersebut sebagai kemenangan runtime langsung atas Botasaurus.

8. Urutan eksekusi berikutnya
Saya merekomendasikan agar pekerjaan teknis dimulai dengan satu milestone yang dapat ditutup sepenuhnya: G0 — Audit Botasaurus dan kemampuan aktual Termux.

Urutannya:

Pin commit source Botasaurus.

Inventaris file Python, package, dependensi, adapter request/browser, dan tes.

Catat kemampuan yang terimplementasi versus yang benar-benar teruji.

Verifikasi transport yang bisa dipasang pada Python di perangkat.

Verifikasi jalur browser Android yang tersedia.

Hasilkan laporan audit dan daftar eksperimen prioritas.

Baru setelah itu buat benchmark fixture dan implementasi classifier.

Hasil G0 harus berupa laporan dengan bukti, bukan kesimpulan bahwa framework baru lebih baik.

Kriteria keputusan utama: jika kita belum bisa menunjukkan skenario yang gagal atau kurang efisien pada baseline Botasaurus, kita belum memiliki dasar yang cukup untuk memilih fitur kompetitif berikutnya. Itulah perbedaan antara blueprint yang panjang dan rencana engineering yang bisa menghasilkan keunggulan terukur.




