import socket, time, csv, sys

SRC = r"C:\Users\User\macedonian_names_latin.txt"
CSV_PATH = r"C:\Users\User\macedonian_domains_status.csv"
OUT_FREE = r"C:\Users\User\macedonian_domains_free.txt"
HOST = "whois.marnet.mk"
PORT = 43
BASE_DELAY = 2.0      # polite gap between queries
READ_TIMEOUT = 20
MAX_RETRIES = 12      # per-name retries with backoff on empty/error

def load_names(path):
    male, female = [], []
    cur = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line == "## MALE": cur = male; continue
            if line == "## FEMALE": cur = female; continue
            if not line or line.startswith("#") or cur is None:
                continue
            for n in line.split(","):
                n = n.strip()
                if n: cur.append(n)
    return male, female

def whois(q):
    """Return response text, or '' on empty/closed. Raises on connect failure."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(READ_TIMEOUT)
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

def load_existing():
    d = {}
    try:
        with open(CSV_PATH, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                d[r["domain"]] = r["status"]
    except FileNotFoundError:
        pass
    return d

def main():
    male, female = load_names(SRC)
    names = [(n, "male") for n in male] + [(n, "female") for n in female]

    existing = load_existing()
    todo = [(n, g) for (n, g) in names if existing.get(f"{n}.mk") not in ("free", "taken")]
    done = [(n, g, existing[f"{n}.mk"]) for (n, g) in names if existing.get(f"{n}.mk") in ("free", "taken")]

    sys.stderr.write(f"resume: {len(done)} already known, {len(todo)} to query\n")
    results = [{"name": n, "gender": g, "domain": f"{n}.mk", "status": st} for (n, g, st) in done]

    for i, (name, gender) in enumerate(todo, 1):
        domain = f"{name}.mk"
        status = "error"
        for attempt in range(MAX_RETRIES):
            try:
                resp = whois(domain)
                status = classify(resp)
            except Exception as e:
                status = "error"
                resp = f"EXC:{e}"
            if status in ("free", "taken"):
                break
            # empty/error -> back off and retry this same name
            backoff = min(2 ** (attempt + 1), 30)
            sys.stderr.write(f"  retry {domain} (att {attempt+1}) empty/err, backoff {backoff}s\n")
            sys.stderr.flush()
            time.sleep(backoff)
        results.append({"name": name, "gender": gender, "domain": domain, "status": status})
        sys.stderr.write(f"[{i}/{len(todo)}] {domain} -> {status}\n")
        sys.stderr.flush()
        time.sleep(BASE_DELAY)

    # write CSV
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "gender", "domain", "status"])
        w.writeheader()
        for r in results:
            w.writerow(r)

    free = [r for r in results if r["status"] == "free"]
    taken = [r for r in results if r["status"] == "taken"]
    unknown = [r for r in results if r["status"] in ("error", "unknown")]

    with open(OUT_FREE, "w", encoding="utf-8") as f:
        f.write(f"# FREE .mk domains (from {len(results)} Macedonian given names)\n")
        f.write(f"# free: {len(free)}   taken: {len(taken)}   error/unknown: {len(unknown)}\n\n")
        for r in sorted(free, key=lambda x: x["domain"]):
            f.write(f"{r['domain']}\n")

    sys.stderr.write("\n==== SUMMARY ====\n")
    sys.stderr.write(f"total={len(results)} free={len(free)} taken={len(taken)} unknown={len(unknown)}\n")
    if unknown:
        sys.stderr.write("UNKNOWN: " + ", ".join(r["domain"] for r in unknown) + "\n")

if __name__ == "__main__":
    main()
