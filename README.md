# Slab Edge

Finds graded (PSA 9 and 10) football cards listed on Fanatics Collect for less than the identical card, in the identical grade, keeps selling for on eBay, after tax, shipping and eBay fees. Publishes picks to GitHub Pages from `docs/`.

## How it works

- **Buy side:** Fanatics Collect fixed-price listings, read from the site's public search index (`cardarb/fanatics.py`).
- **Sell side:** eBay sold prices per exact card and grade, scraped from SportsCardsPro (`cardarb/scp.py`).
- **Filter:** `cardarb/scan.py` holds every rule and cost as a constant at the top.
- **Network:** every request goes through a SOCKS tunnel to scotus-vps (`cardarb-tunnel.service`, `127.0.0.1:1088`). eBay, PSA, 130point, MySlabs and COMC block that IP, so they are not used.

## Running (a6000-box)

```
~/cardarb/.venv/bin/python -m cardarb.scan      # one scan, writes docs/data/
systemctl --user status cardarb-scan.timer      # every 30 min, scan then push
```
