#!/usr/bin/env python
"""
mk_dashboard.py  -  .mk domain availability dashboard (stdlib only)
Serves a single-page dashboard + a JSON API backed by domains.json.
WHOIS is queried live against the MARnet registry (whois.marnet.mk, port 43).
The registry silently rate-limits rapid bursts, so check_one() retries with
exponential backoff on empty responses.

Endpoints:
  GET  /                 -> dashboard HTML
  GET  /api/list         -> {records:[...], stats:{...}}
  POST /api/check        -> body {"names":["foo","bar"]}  (one or many)
  GET  /api/recheck/<name>  -> {"name":...,"status":...}
"""
import json, os, socket, threading, time, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "domains.json")
HOST, PORT = "whois.marnet.mk", 43

_lock = threading.RLock()

def load():
    try:
        with open(DB, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"records": {}, "updated": ""}

def save(db):
    db["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tmp = DB + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB)

def whois_raw(q, timeout=20):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((HOST, PORT))
    try:
        s.sendall((q + "\r\n").encode())
        data = b""
        while True:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk
        return data.decode(errors="replace")
    finally:
        try: s.close()
        except Exception: pass

def classify(resp):
    if not resp or not resp.strip():
        return "error"
    if "ERROR:101" in resp or "No entries found" in resp:
        return "free"
    if "domain:" in resp:
        return "taken"
    return "unknown"

def check_one(name, delay=1.0):
    """Return status string. Retry with backoff on empty/error."""
    domain = f"{name}.mk" if not name.endswith(".mk") else name
    bare = domain[:-3]
    time.sleep(delay)
    last = "error"
    for attempt in range(10):
        try:
            resp = whois_raw(domain)
            last = classify(resp)
        except Exception:
            last = "error"
        if last in ("free", "taken"):
            return last
        time.sleep(min(2 ** (attempt + 1), 30))
    return last

# Macedonian Latin diacritics -> ASCII (latin keyboard)
_TR = {ord("Č"):"C", ord("č"):"c", ord("Š"):"S", ord("š"):"s",
       ord("Ž"):"Z", ord("ž"):"z", ord("Ć"):"C", ord("ć"):"c",
       ord("Đ"):"D", ord("đ"):"d"}

def ascii_latin(s):
    """Strip Macedonian diacritics to plain ASCII Latin keyboard form."""
    return s.translate(_TR)

def stats(records):
    from collections import Counter
    c = Counter(v.get("status", "error") for v in records.values())
    g = Counter(v.get("gender", "?") for v in records.values())
    return {
        "total": len(records),
        "free": c.get("free", 0),
        "taken": c.get("taken", 0),
        "error": c.get("error", 0) + c.get("unknown", 0),
        "male": g.get("male", 0),
        "female": g.get("female", 0),
    }

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype):
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_GET(self):
        p = urlparse(self.path)
        if p.path in ("/", "/index.html"):
            self._send_file(os.path.join(BASE, "index.html"), "text/html")
        elif p.path == "/api/list":
            db = load()
            self._send(200, json.dumps({"records": list(db["records"].values()),
                                        "stats": stats(db["records"])}))
        elif p.path.startswith("/api/recheck/"):
            name = unquote(p.path.split("/api/recheck/", 1)[1])
            db = load()
            with _lock:
                rec = db["records"].get(name)
                if not rec:
                    ln = name.lower()
                    rec = next((v for k, v in db["records"].items()
                                if k.lower() == ln), None)
            if not rec:
                self._send(404, json.dumps({"error": "not found"}))
                return
            status = check_one(rec["domain"])
            with _lock:
                rec["status"] = status
                rec["source"] = "recheck"
                save(db)
            self._send(200, json.dumps({"name": name, "domain": rec["domain"], "status": status}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        p = urlparse(self.path)
        if p.path != "/api/check":
            self._send(404, json.dumps({"error": "not found"}))
            return
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n).decode("utf-8") if n else "{}"
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {}
        names = payload.get("names", [])
        if isinstance(names, str):
            names = [names]
        # normalize: split on commas/whitespace, strip, drop empties
        cleaned = []
        for part in names:
            for tok in str(part).replace(",", " ").split():
                tok = ascii_latin(tok).strip().strip(".").lower()
                if tok and tok not in cleaned:
                    cleaned.append(tok)

        db = load()
        results = []
        with _lock:
            # case-insensitive index so re-adds update in place (no dupes)
            lc_index = {k.lower(): k for k in db["records"]}
            for i, name in enumerate(cleaned):
                domain = f"{name}.mk"
                status = check_one(name, delay=0.5 if i else 1.0)
                existing_key = lc_index.get(name)
                if existing_key:
                    rec = db["records"][existing_key]
                    rec["status"] = status
                    rec["source"] = "manual-add"
                    key = existing_key
                else:
                    key = name
                    db["records"][key] = {
                        "name": name, "gender": "?",
                        "domain": domain, "status": status,
                        "source": "manual-add",
                    }
                    lc_index[name] = key
                results.append({"name": name, "domain": domain, "status": status})
            save(db)

        self._send(200, json.dumps({"results": results, "stats": stats(db["records"])}))

if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", 8765), H)
    print("Dashboard: http://127.0.0.1:8765/")
    print("DB:", DB)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
