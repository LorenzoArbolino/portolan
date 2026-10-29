# Source notes

What each data source can and can't give, tested on real documents before the pipeline relied on it.

| Source | Result | One line |
|---|---|---|
| [China EIA](china-eia.md) | partially proven (3 of 5 target docs) | Company-posted environmental disclosures and EIA notices give t/a per site (NHU Weifang: 15,000 t/a citral); full EIA reports exist but blank out capacities |
| [India EC at scale](india-environmental-clearances.md) | proven (10 docs, 4 with scanned pages) | Product-wise MT/Month tables; layout text is essential; OCR fine for prose, poor for scanned tables (scanned tables need a vision model); national portal blocked by TLS/network |
| [DRHP / RHP](india-prospectuses.md) | proven (3 RHPs) | Chartered-engineer-certified installed capacity, production and utilisation per facility and product category, from SEBI's document store |
| [EPA CDR](us-epa-cdr.md) | proven, with limits | Site-level production volumes are public unless CBI; 40 US kraft mills publish turpentine output; no US citral manufacture |
| [flows](trade-flows.md) | proven | Comtrade preview (keyless, 1 year per call, slow) and Eurostat Comext (keyless, many years per call) |
| [EU trade defence](eu-trade-defence.md) | proven | CELLAR serves the acts; Article 1 duty tables parse; Union-industry tables are ranges when one producer dominates |

Pipeline fixes these tests and the gold run led to: declared-charset decoding (GBK), layout PDF text for agents,
OCR fallback, partial dates in agent output, agents isolated from repository instructions, fetch retries.
