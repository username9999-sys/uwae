#!/usr/bin/env python
"""E6 — Regression test: isu publik Botasaurus — infinite retry pada kegagalan resolusi DNS.

Target: botasaurus_requests 4.0.38 di /root/botasaurus-venv (baseline ter-pin 6c9260de).

Mode (dipilih via argv[1], diorkestrasi induk dengan `timeout`):
  t1t3 — bukti source (while True tanpa batas) + kontrol error non-DNS
  t4   — DNS failure nyata: apakah pesan error cocok dengan kondisi retry
  t2   — error DNS crafted: observasi retry berulang (induk kill dengan timeout
         jika tidak berterminasi -> bukti unbounded)

Catatan: bagian "Cloudflare bypass timeout" dari isu publik tidak diuji di sini
(membutuhkan target ber-CF dengan otorisasi eksplisit).
"""
import sys
import time


def t1_source_evidence():
    import inspect

    from botasaurus_requests import reqs

    src = inspect.getsource(reqs.retry_on_network_error)
    while_true = "while True" in src
    dns_match = "'dial tcp: lookup'" in src and "'no such host'" in src
    bounded = any(k in src for k in ("max_retry", "range(", "count", "break"))
    print(f"T1 source: while True={while_true}, dns-match={dns_match}, ada-batas={bounded}", flush=True)
    verdict = "UNBOUNDED (while True tanpa batas retry)" if while_true and not bounded else "bounded"
    print(f"T1 VERDICT: {verdict}", flush=True)


def t3_control_non_dns():
    from botasaurus_requests import reqs

    def other_error():
        raise Exception("connection refused")

    try:
        reqs.retry_on_network_error(other_error)
        print("T3: tidak di-raise (TIDAK DIHARAPKAN)", flush=True)
    except Exception as e:
        print(f"T3 kontrol OK: error non-DNS langsung di-raise ({str(e)[:40]})", flush=True)


def t4_real_dns_failure():
    from botasaurus_requests import reqs

    print("T4: get() ke domain .invalid yang tidak ada...", flush=True)
    try:
        reqs.get("https://nonexistent-uwae-e6-test.invalid", timeout=10)
        print("T4: tidak error (tidak diharapkan)", flush=True)
    except Exception as e:
        msg = str(e)
        matches = ("dial tcp: lookup" in msg) and ("no such host" in msg)
        print(f"T4 pesan error: {msg[:150]}", flush=True)
        print(f"T4 cocok kondisi retry: {matches}", flush=True)


def t2_crafted_dns_error():
    from botasaurus_requests import reqs

    n = {"i": 0}

    def failing():
        n["i"] += 1
        print(f"T2 attempt #{n['i']}: raise crafted DNS error", flush=True)
        raise Exception("dial tcp: lookup nonexistent.invalid: no such host")

    print("T2: mulai (induk akan kill dengan timeout jika infinite)", flush=True)
    reqs.retry_on_network_error(failing)
    print("T2: selesai (berarti bounded)", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "t1t3":
        t1_source_evidence()
        t3_control_non_dns()
    elif mode == "t4":
        t4_real_dns_failure()
    elif mode == "t2":
        t2_crafted_dns_error()
    else:
        print(f"mode tidak dikenal: {mode}", flush=True)
        sys.exit(2)
