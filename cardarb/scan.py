"""One scan: find listings that clear every cost at the low end of recent exact-card sales."""
import json
import os
import re
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import fanatics, net, scp

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
CACHE = ROOT / "cache"

# Costs. Buying on Fanatics Collect, reselling on eBay.
TAX = 0.09375            # San Mateo County sales tax on the purchase
SHIP_IN = 10.00          # Fanatics shipping to you (vault-to-door, conservative)
EBAY_FEE = 0.1325        # eBay final value fee for trading cards (under $7,500)
EBAY_ORDER_FEE = 0.40
SHIP_OUT = 6.00          # bubble mailer, team bag, top loader, tracked postage

# Bar every pick has to clear.
WINDOW_DAYS = 60         # sales that count as "recent"
MIN_SALES = 6            # at least this many exact-card, exact-grade sales in the window
FLOOR_PCT = 0.20         # resale assumed at the 20th percentile of recent sales
MIN_PROFIT = 20.00       # dollars, after every cost, at the floor price
MIN_ROI = 0.20           # and at least 20% on what you paid
TOO_GOOD = 0.40          # asking under 40% of the median is more likely a mismatch than a gift
MAX_DOWNTREND = 0.10     # last 30 days' median may sit at most 10% under the prior 60

GRADERS = ["PSA"]
GRADES = [9, 10]
PRICE_LO, PRICE_HI = 25, 5000
PREFILTER_RATIO = 1.20   # Fanatics listings at or under 120% of their own guide value
GUIDE_LO, GUIDE_HI = 0.6, 1.6  # Fanatics' guide must land within this band of the eBay median


def worth_checking(h):
    """Cheap pre-check: could this clear the bar even at the highest median the guide allows?"""
    guide = float(h.get("value") or 0)
    c = cost(float(h["askingPrice"]))
    return guide > 0 and proceeds(guide / GUIDE_LO) - c >= max(MIN_PROFIT, MIN_ROI * c)


def cost(ask):
    return ask * (1 + TAX) + SHIP_IN


def proceeds(sale):
    return sale * (1 - EBAY_FEE) - EBAY_ORDER_FEE - SHIP_OUT


def pct(xs, q):
    xs = sorted(xs)
    i = (len(xs) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def load(p, default):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def cached(name, ttl, fn):
    """Small JSON cache so repeat scans don't re-fetch the same SportsCardsPro pages."""
    CACHE.mkdir(exist_ok=True)
    p = CACHE / (re.sub(r"[^A-Za-z0-9]+", "_", name)[:150] + ".json")
    hit = load(p, None)
    if hit and time.time() - hit["t"] < ttl:
        return hit["v"]
    v = fn()
    p.write_text(json.dumps({"t": time.time(), "v": v}, default=str))
    return v


def query_for(h):
    t = re.split(r"\b(PSA|BGS|SGC|CGC)\b", h["title"])[0]
    return re.sub(r"\s+", " ", t).strip()


def evaluate(s, h, today):
    """Return (pick_dict, None) or (None, reason)."""
    title = h["title"]
    if not worth_checking(h):
        return None, "cannot clear the bar"
    if scp.QUALIFIER.search(title):
        return None, "qualified grade"
    cands = cached("q_" + query_for(h), 7 * 86400,
                   lambda: scp.search(s, query_for(h)))
    m = scp.match(h, cands)
    if not m:
        return None, "no exact product match"
    url, name, setname = m
    grade = int(h["grade"])
    raw = cached(f"s_{url}_{grade}", 6 * 3600,
                 lambda: [(d.isoformat(), p, t, u) for d, p, t, u in scp.sales(s, url, grade)])
    sales = [(date.fromisoformat(d), p, t, u) for d, p, t, u in raw]
    recent = [x for x in sales if (today - x[0]).days <= WINDOW_DAYS]
    if len(recent) < MIN_SALES:
        return None, f"thin market ({len(recent)} sales)"
    prices = [x[1] for x in recent]
    med = statistics.median(prices)
    floor = pct(prices, FLOOR_PCT)
    last30 = [x[1] for x in recent if (today - x[0]).days <= 30]
    prior = [x[1] for x in sales if 30 < (today - x[0]).days <= 90]
    if len(last30) >= 3 and len(prior) >= 3 and statistics.median(last30) < (1 - MAX_DOWNTREND) * statistics.median(prior):
        return None, "falling price"
    ask = float(h["askingPrice"])
    if ask < TOO_GOOD * med:
        return None, "too far under market (likely mismatch)"
    guide = float(h.get("value") or 0)
    if guide and not (GUIDE_LO * med <= guide <= GUIDE_HI * med):
        return None, "sources disagree"
    c = cost(ask)
    profit = proceeds(floor) - c
    if profit < MIN_PROFIT or profit < MIN_ROI * c:
        return None, "margin too small"
    return {
        "id": h["listingId"],
        "title": title,
        "product": f"{name} · {setname}".replace(" (Football)", ""),
        "grade": f"{h['gradingService']} {grade}",
        "cert": h.get("serial"),
        "image": (h.get("images") or {}).get("primary", {}).get("small"),
        "buy_url": fanatics.url(h),
        "comps_url": url,
        "ask": round(ask, 2),
        "all_in_cost": round(c, 2),
        "floor": round(floor, 2),
        "median": round(med, 2),
        "low": round(min(prices), 2),
        "sales_n": len(recent),
        "fanatics_guide": round(guide, 2) if guide else None,
        "profit": round(profit, 2),
        "roi": round(profit / c, 3),
        "profit_at_median": round(proceeds(med) - c, 2),
        "recent_sales": [{"date": d.isoformat(), "price": p, "url": u}
                         for d, p, _, u in sorted(recent, reverse=True)[:12]],
        "allow_offers": bool(h.get("allowOffers")),
    }, None


def track(s, history, today):
    """For picks at least 14 days old, check what the card actually sold for since."""
    for p in history.values():
        if p.get("outcome") or (today - date.fromisoformat(p["first_seen"][:10])).days < 14:
            continue
        g = int(p["grade"].split()[-1])
        try:
            after = [x for x in scp.sales(s, p["comps_url"], g)
                     if x[0] > date.fromisoformat(p["first_seen"][:10])]
        except net.Blocked:
            return
        if len(after) >= 3:
            med = statistics.median(x[1] for x in after)
            p["outcome"] = {"checked": today.isoformat(), "sales_after": len(after),
                            "median_after": round(med, 2),
                            "profit_after": round(proceeds(med) - p["all_in_cost"], 2)}


def main():
    now = datetime.now(timezone.utc)
    today = now.date()
    s = net.session()
    DATA.mkdir(parents=True, exist_ok=True)
    history = load(DATA / "history.json", {})
    picks, reasons, checked = [], {}, 0
    errors = []
    for h in fanatics.listings(s, GRADERS, GRADES, PRICE_LO, PRICE_HI, PREFILTER_RATIO):
        checked += 1
        if checked > int(os.environ.get("CARDARB_LIMIT", 10**9)):
            break
        try:
            pick, why = evaluate(s, h, today)
        except net.Blocked as e:
            errors.append(str(e))
            break
        if pick:
            picks.append(pick)
            print(f"PICK +${pick['profit']:.0f} {pick['title']}", flush=True)
        else:
            reasons[why] = reasons.get(why, 0) + 1
    picks.sort(key=lambda p: -p["profit"])

    live = {p["id"] for p in picks}
    for p in picks:
        old = history.get(p["id"], {})
        history[p["id"]] = {**p, "first_seen": old.get("first_seen", now.isoformat()),
                            "last_seen": now.isoformat(), "status": "live",
                            **({"outcome": old["outcome"]} if old.get("outcome") else {})}
        p["first_seen"] = history[p["id"]]["first_seen"]
    for k, p in history.items():
        if k not in live and p.get("status") == "live":
            p["status"] = "gone"
            p["gone_at"] = now.isoformat()
    track(s, history, today)

    (DATA / "picks.json").write_text(json.dumps({
        "updated": now.isoformat(), "checked": checked, "rejected": reasons,
        "errors": errors, "picks": picks,
        "rules": {"window_days": WINDOW_DAYS, "min_sales": MIN_SALES, "floor_pct": FLOOR_PCT,
                  "min_profit": MIN_PROFIT, "min_roi": MIN_ROI, "tax": TAX, "ship_in": SHIP_IN,
                  "ebay_fee": EBAY_FEE, "ship_out": SHIP_OUT},
    }, indent=1))
    (DATA / "history.json").write_text(json.dumps(history, indent=1))
    print(f"checked {checked}, picks {len(picks)}, rejected {reasons}, errors {errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
