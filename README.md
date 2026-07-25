# iminja.mk — .mk Domain Availability Dashboard

A dashboard that checks which Macedonian given names are available as `.mk` domains.

**Live site:** https://kindzadzaski.github.io/iminja.mk/

## How it works

- **Data source:** WHOIS lookups against `whois.marnet.mk` (MARnet registry)
- **Name list:** 147 male + 141 female Macedonian given names in Latin script (from behindthename.com and Wikipedia)
- **Output:** Static snapshot displayed as a searchable/filterable dashboard

## Files

| File | Purpose |
|------|---------|
| `index.html` | Static frontend dashboard (works on GitHub Pages) |
| `data.json` | Pre-computed domain records + stats |
| `domains.json` | Raw database (used by the Python backend) |
| `mk_dashboard.py` | Python HTTP server with live WHOIS checking |
| `check_mk_domains.py` | Bulk WHOIS scanner for initial data collection |
| `macedonian_names_latin.txt` | Source name list |

## Running the live server

To run the backend with live WHOIS re-checks:

```bash
python mk_dashboard.py
```

Then open http://127.0.0.1:8765/

## Regenerating data

To refresh the data from scratch:

```bash
python check_mk_domains.py
python -c "
import json; from collections import Counter
db = json.load(open('domains.json'))
records = list(db['records'].values())
c = Counter(v.get('status','error') for v in records)
g = Counter(v.get('gender','?') for v in records)
stats = {'total':len(records),'free':c.get('free',0),'taken':c.get('taken',0),
         'error':c.get('error',0)+c.get('unknown',0),'male':g.get('male',0),'female':g.get('female',0)}
json.dump({'records':records,'stats':stats}, open('data.json','w'), indent=2)
"
```
