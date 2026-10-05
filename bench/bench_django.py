"""Django bench driver: same shape as bench_http.py (N threads, 1 path each).

Login is done once and the session cookie shared across threads (Django
rate-limits logins per IP, so per-thread login would 429). POSTs carry
the session's CSRF token like the Rails forms do.
"""

import re
import statistics
import sys
import threading
import time

import requests

TOKEN_RE = re.compile(r'authenticity_token" value="([^"]+)"')


def login(base, email, password):
    sess = requests.Session()
    page = sess.get(base + "/session/new", timeout=30).text
    token = TOKEN_RE.search(page).group(1)
    r = sess.post(base + "/session",
                  data={"email_address": email, "password": password,
                        "authenticity_token": token},
                  timeout=30, allow_redirects=False)
    assert r.status_code == 302, r.status_code
    room = sess.get(base + "/", timeout=30, allow_redirects=False)
    assert room.status_code == 302, room.status_code
    rid = room.headers["Location"].rsplit("/", 1)[-1]
    csrf = TOKEN_RE.search(sess.get(base + "/rooms/" + rid,
                                    timeout=30).text).group(1)
    cookies = sess.cookies.get_dict()
    return cookies, csrf, rid


def worker(method, url, payload, count, out, errors, cookies, csrf):
    sess = requests.Session()
    sess.cookies.update(cookies)
    headers = {"X-CSRF-Token": csrf} if method == "POST" else {}
    lat = []
    ok = 0
    for i in range(count):
        t = time.perf_counter()
        try:
            if method == "GET":
                r = sess.get(url, timeout=30)
            else:
                data = dict(payload)
                data["message[client_message_id]"] = "bench-%d-%d" % (i, ok)
                r = sess.post(url, data=data, headers=headers, timeout=30)
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


def drive(base, path, method, url, payload, concurrency, count, cookies, csrf):
    out, errors = [], []
    threads = [threading.Thread(target=worker, args=(
        method, url, payload, count, out, errors, cookies, csrf))
        for _ in range(concurrency)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    dt = time.perf_counter() - t0
    oks = sum(o for o, _ in out)
    lats = sorted(l for _, ls in out for l in ls)
    p50 = lats[len(lats) // 2] if lats else 0
    p99 = lats[int(len(lats) * 0.99)] if lats else 0
    print("%-8s c=%-4d %7.1f req/s  p50=%6.2fms p99=%6.2fms err=%d %s"
          % (path, concurrency, oks / dt, p50, p99, len(errors),
             str(errors[:3]) if errors else ""))


base = sys.argv[1]
concurrency = int(sys.argv[2]) if len(sys.argv) > 2 else 12
count = int(sys.argv[3]) if len(sys.argv) > 3 else 20
cookies, csrf, rid = login(base, "user0@example.com", "password")
print("login ok, room", rid)
paths = {
    "room": ("GET", "%s/rooms/%s" % (base, rid), None),
    "messages": ("GET", "%s/rooms/%s/messages" % (base, rid), None),
    "sidebar": ("GET", "%s/users/me/sidebar" % base, None),
    "search": ("GET", "%s/searches?q=coffee" % base, None),
    "post": ("POST", "%s/rooms/%s/messages" % (base, rid),
             {"message[body]": "bench hello coffee"}),
}
wanted = sys.argv[4].split(",") if len(sys.argv) > 4 else list(paths)
for name in wanted:
    method, url, payload = paths[name]
    drive(base, name, method, url, payload, concurrency, count, cookies, csrf)
