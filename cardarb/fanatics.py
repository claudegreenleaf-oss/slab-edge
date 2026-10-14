"""Buy side: live fixed-price football listings on Fanatics Collect (public Algolia index)."""
from . import net

GQL = "https://app.fanaticscollect.com/graphql?webSearchKeyQuery"
ALGOLIA = "https://3xt9c4x62i-dsn.algolia.net/1/indexes/*/queries"
APP_ID = "3XT9C4X62I"
INDEX = "prod_item_state_v1_price_asc"
ORIGIN = {"origin": "https://www.fanaticscollect.com", "referer": "https://www.fanaticscollect.com/"}


def _key(s):
    q = {"operationName": "webSearchKeyQuery", "variables": {},
         "query": "query webSearchKeyQuery { collectSearchKeyV2 { key validUntil } }"}
    r = s.post(GQL, json=q, headers=ORIGIN, timeout=30)
    r.raise_for_status()
    return r.json()["data"]["collectSearchKeyV2"]["key"]


def listings(s, graders, grades, lo, hi, max_ratio):
    """Yield listings priced at or below max_ratio of Fanatics' own guide value.

    Algolia caps a query at 1000 hits, so the price range is walked in bands.
    """
    gf = " OR ".join(f'gradingService:"{g}"' for g in graders)
    gr = [f"grade={g}" for g in grades]
    flt = ('(marketplace:"FIXED") AND (status:"Live") AND (subCategory1:"Sports Cards > Football") '
           f"AND ({gf}) AND (NOT visibility:internal)")
    seen = set()
    bands = [lo, 35, 50, 75, 100, 150, 200, 300, 400, 600, 800, 1200, 1600, 2500, hi]
    bands = [b for b in bands if lo <= b <= hi]
    for a, b in zip(bands, bands[1:]):
        # The search key expires within the hour and a full scan runs longer, so refresh per band.
        headers = {**ORIGIN, "x-algolia-api-key": _key(s), "x-algolia-application-id": APP_ID}
        for page in range(10):  # Algolia stops serving past hit 1000
            body = {"requests": [{
                "indexName": INDEX, "query": "", "hitsPerPage": 100, "page": page,
                "filters": flt,
                "numericFilters": [f"askingPrice>={a}", f"askingPrice<{b}",
                                   f"guidePriceRatio<={max_ratio}", "guidePriceRatio>0", gr],
            }]}
            net.polite("algolia", 1.0)
            r = s.post(ALGOLIA, json=body, headers=headers, timeout=30)
            if r.status_code != 200:
                print(f"fanatics search {r.status_code} at ${a}-{b} page {page}: {r.text[:200]}", flush=True)
                break
            res = r.json()["results"][0]
            for h in res["hits"]:
                if h["listingId"] in seen:
                    continue
                seen.add(h["listingId"])
                yield h
            if page + 1 >= res.get("nbPages", 0):
                break


def url(h):
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", h["title"].lower()).strip("-")
    return f"https://www.fanaticscollect.com/buy-now/{h['listingId']}/{slug}"
