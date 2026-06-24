# Mock quote fixtures (demo data)

Synthetic, ready-to-use quote payloads for the demo — **no real customer or insurer
brand data** (vehicle makes/models follow the brief's own worked-example style, e.g.
"Ford Focus"). Each file is a **whole-model quote body** (brief §11 fields) that can be
applied to a quote as a patch.

| File | Profile | Expected outcome (once pricing/underwriting lands — Slice 5) |
|---|---|---|
| `standard-quote.json` | 34-yo, Ford Focus, comprehensive, 5 yrs NCD, no claims | **QUOTE** |
| `young-driver-quote.json` | Under-25 student driver, 1 yr NCD | **QUOTE** (young-driver loading) |
| `referral-high-value.json` | Vehicle value > £75,000 | **REFER** |
| `decline-under-age.json` | Under-18 driver | **DECLINE** |

The `_scenario` field in each file is a human note and is ignored by the platform.

## How to use (against the running platform on :8070)

```bash
# 1) create a quote → grab quoteId + sessionId
RESP=$(curl -s -XPOST localhost:8070/quotes)
QID=$(echo "$RESP" | sed -n 's/.*"quoteId":"\([^"]*\)".*/\1/p')
SID=$(echo "$RESP" | sed -n 's/.*"sessionId":"\([^"]*\)".*/\1/p')

# 2) apply a fixture as the patch (strip the _scenario note as needed)
curl -s -XPATCH localhost:8070/quotes/$QID \
  -H "X-Session-Id: $SID" -H 'content-type: application/json' \
  -d "{\"patch\": $(cat standard-quote.json) }"

# 3) (once Slice 5 lands) price it
curl -s -XPOST localhost:8070/quotes/$QID/price -H "X-Session-Id: $SID"
```

These also back the brief's demonstration scenarios (§19) and the §15 underwriting
rules. A future `POST /quotes/seed/{scenario}` endpoint could load one of these
directly for one-click demos.
