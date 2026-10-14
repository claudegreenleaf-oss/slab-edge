"""Sell side: eBay sold prices per exact card and grade, scraped from SportsCardsPro."""
import re
from datetime import date
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from . import net

HOST = "www.sportscardspro.com"
BASE = f"https://{HOST}"

# Words that mark a parallel, insert or variation. A listing that carries one of these
# must be matched to a SportsCardsPro product that names it, or it is not the same card.
PARALLEL = set("""
silver gold red blue green orange purple pink black white bronze teal aqua yellow lime
holo refractor wave shimmer mojo ice cracked disco hyper tie dye camo neon sparkle scope
lazer laser choice fast break snakeskin velocity pulsar sepia auto autograph autographs
patch jersey relic relics ssp sp variation var image die cut xfractor atomic prizms
shock stars stained glass kaboom downtown color blast genesis zebra tiger dragon
press proof fotl first off line 1st edition superfractor logo printing plate plates
camo mosaic wave wild card gem masterpiece numbered serial negative photo variant signed dna
""".split())
# Never let these count as parallel words (they are set names, rookie tags or grades).
NEUTRAL = {"prizm", "mosaic", "rookie", "rc", "psa", "gem", "mint", "mt", "nm", "card", "football", "nfl"}
QUALIFIER = re.compile(r"\b(oc|mc|st|pd|of|mk)\b|\(\s*(oc|mc|st|pd|of|mk)\s*\)", re.I)
BAD_SALE = re.compile(r"\b(lot|lots|bgs|sgc|cgc|beckett|csg|hga|tag|reprint|custom|x\s?\d|\(\d\))\b", re.I)


def toks(s):
    return set(re.findall(r"[a-z0-9]+", s.lower().replace("-", " ")))


def serials(s):
    return set(re.findall(r"/\s*(\d{1,4})\b", s))


def search(s, query):
    """Return [(product_url, name, set_name)] for a search, following direct product redirects."""
    r = net.get(s, f"{BASE}/search-products?q={quote_plus(query)}&type=prices", HOST)
    if r is None:
        return []
    if "/game/" in r.url:
        if "football-cards" not in r.url:
            return []
        b = BeautifulSoup(r.text, "html.parser")
        h1 = b.select_one("h1#product_name") or b.select_one("h1")
        if not h1:
            return []
        crumb = h1.select_one("a")
        setname = crumb.get_text(" ", strip=True) if crumb else ""
        name = h1.get_text(" ", strip=True)
        if setname and name.endswith(setname):
            name = name[: -len(setname)].strip()
        return [(r.url.split("?")[0], name, setname + " (Football)")]
    b = BeautifulSoup(r.text, "html.parser")
    out = []
    for tr in b.select("table#games_table tr[id]"):
        a = tr.select_one("td.title a[href*='/game/']")
        con = tr.select_one("td.console")
        if a:
            out.append((a["href"] if a["href"].startswith("http") else BASE + a["href"],
                        a.get_text(" ", strip=True), con.get_text(" ", strip=True) if con else ""))
    return out


def match(listing, cands):
    """Pick the one SportsCardsPro product that is exactly this card, or None."""
    title = listing["title"]
    lt = toks(title)
    year = str(listing.get("year") or "")
    num = str(listing.get("cardNumber") or "").lstrip("#").lower()
    if not num:
        m = re.search(r"#\s*([A-Za-z0-9-]+)", title)
        num = m.group(1).lower() if m else ""
    hits = []
    for url, name, setname in cands:
        if "football" not in setname.lower() or not setname.startswith(year):
            continue
        m = re.search(r"#\s*([A-Za-z0-9-]+)", name)
        if not num or not m or m.group(1).lower() != num:
            continue
        player = toks(re.split(r"[\[#]", name)[0]) - NEUTRAL
        if not player or not player <= lt:
            continue
        variant = toks(" ".join(re.findall(r"\[([^\]]+)\]", name))) - NEUTRAL
        set_t = toks(re.sub(r"\(.*?\)", "", setname)) - {year}
        brand_words = {"panini", "topps", "donruss", "leaf", "upper", "deck", "score", "fleer", "bowman"}
        if not (set_t - brand_words) <= lt:  # set name words must appear in the listing
            continue
        if not variant <= lt:  # every product variant word must appear in the listing
            continue
        extra = (lt & PARALLEL) - NEUTRAL - variant - set_t - player
        if extra:  # listing names a parallel this product does not have
            continue
        if serials(title) != serials(name):
            continue
        hits.append((url, name, setname))
    return hits[0] if len(hits) == 1 else None


TAB = {10: "completed-auctions-manual-only", 9: "completed-auctions-graded",
       8: "completed-auctions-new", 7: "completed-auctions-cib"}


def sales(s, url, grade):
    """eBay sales of this product in PSA `grade`: [(date, price, title, ebay_url)]."""
    r = net.get(s, url, HOST)
    if r is None:
        return []
    b = BeautifulSoup(r.text, "html.parser")
    g = int(grade)
    want = re.compile(rf"\bPSA\s*{g}(?![.\d])", re.I)
    out, seen = [], set()
    for div in b.select(f"div.{TAB[g]}"):
        for tr in div.select("tr[id]"):
            if tr["id"] in seen:
                continue
            seen.add(tr["id"])
            d = tr.select_one("td.date")
            a = tr.select_one("td.title a")
            p = tr.select_one("span.js-price")
            if not (d and a and p):
                continue
            t = a.get_text(" ", strip=True)
            if not want.search(t) or BAD_SALE.search(t) or QUALIFIER.search(t):
                continue
            try:
                when = date.fromisoformat(d.get_text(strip=True))
                price = float(p.get_text(strip=True).replace("$", "").replace(",", ""))
            except ValueError:
                continue
            out.append((when, price, t, a["href"].split("?")[0]))
    return out
