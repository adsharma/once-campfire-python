"""Concurrent HTTP load driver (stdlib + requests).

Mirrors bench/compare_http.rb paths: room, messages, sidebar, search, post.
Each worker thread keeps one requests.Session (keep-alive) and loops its
path; reports per-path req/sec plus p50/p99 latency.

Usage:
  python bench_http.py BASE_URL [--concurrency 1,16] [--requests 200] [--paths room,messages,sidebar,search,post]
"""

import json
import statistics
import sys
import threading
import time

import requests

PATHS = ["room", "messages", "sidebar", "search", "post"]


def build_targets(base, meta):
    wc = meta["watercooler"]
    uid = meta["first_user"]
    busy = meta["busy_message"]
    return {
        "room": ("GET", "%s/rooms/%d?as=%d" % (base, wc, uid), None),
        "messages": ("GET", "%s/rooms/%d/messages?before=%d&as=%d" % (base, wc, busy, uid), None),
        "sidebar": ("GET", "%s/users/me/sidebar?as=%d" % (base, uid), None),
        "search": ("GET", "%s/searches?q=coffee&as=%d" % (base, uid), None),
        "post": ("POST", "%s/rooms/%d/messages" % (base, wc),
                 {"creator_id": uid, "body": "bench hello coffee world"}),
    }


def worker(method, url, payload, count, out, errors):
    sess = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=1)
    sess.mount("http://", adapter)
    lat = []
    ok = 0
    for _ in range(count):
        t = time.perf_counter()
        try:
            if method == "GET":
                r = sess.get(url, timeout=30)
            else:
                r = sess.post(url, json=payload, timeout=30)
            dt = time.perf_counter() - t
            if r.status_code in (200, 201):
                ok += 1
                lat.append(dt * 1000.0)
            else:
                errors.append(r.status_code)
            r.content
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
    out.append((ok, lat))


def drive(base, path, method, url, payload, concurrency, count):
    threads = []
    out = []
    errors = []
    per = max(1, count // concurrency)
    t0 = time.perf_counter()
    for _ in range(concurrency):
        th = threading.Thread(target=worker, args=(method, url, payload, per, out, errors))
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    dt = time.perf_counter() - t0
    total_ok = sum(o for o, _ in out)
    all_lat = sorted(l for _, ls in out for l in ls)
    result = {
        "path": path,
        "concurrency": concurrency,
        "requests": total_ok,
        "seconds": round(dt, 3),
        "req_per_sec": round(total_ok / dt, 1) if dt > 0 else 0.0,
        "errors": len(errors),
    }
    if all_lat:
        result["p50_ms"] = round(statistics.median(all_lat), 2)
        idx = min(len(all_lat) - 1, int(len(all_lat) * 0.99))
        result["p99_ms"] = round(all_lat[idx], 2)
    return result


def main() -> int:
    base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:5057"
    concurrencies = [1, 16]
    count = 200
    wanted = list(PATHS)
    argv = sys.argv[2:]
    rest = []
    for arg in argv:
        if arg in ("--concurrency", "--requests", "--paths"):
            rest.append(arg + "=")
        elif rest and rest[-1].endswith("="):
            rest[-1] = rest[-1] + arg
        else:
            rest.append(arg)
    for arg in rest:
        if arg.startswith("--concurrency="):
            concurrencies = [int(x) for x in arg.split("=", 1)[1].split(",") if x]
        elif arg.startswith("--requests="):
            count = int(arg.split("=", 1)[1])
        elif arg.startswith("--paths="):
            wanted = arg.split("=", 1)[1].split(",")
    meta = requests.get(base + "/__meta", timeout=30).json()
    print("meta: %s" % json.dumps(meta), flush=True)
    targets = build_targets(base, meta)
    results = []
    for path in wanted:
        method, url, payload = targets[path]
        # Warmup.
        drive(base, path, method, url, payload, 1, 10)
        for conc in concurrencies:
            res = drive(base, path, method, url, payload, conc, count)
            results.append(res)
            print("%-8s c=%-3d %8.1f req/s  p50=%6.2fms p99=%6.2fms err=%d" % (
                path, conc, res["req_per_sec"], res.get("p50_ms", 0),
                res.get("p99_ms", 0), res["errors"]), flush=True)
    print(json.dumps({"meta": meta, "results": results}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
