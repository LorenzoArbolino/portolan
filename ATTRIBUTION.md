# Attribution

Portolan data: © Portolan contributors, available under the Open Database License (ODbL) v1.0 (see `DATA_LICENSE.md`).

Every value in Portolan cites its own source (URL, publisher, date and a short verbatim quote) in `data/evidence.jsonl`. The sources below are those whose terms ask for attribution of the dataset as a whole. This file travels with every release.

| Source | Used for | Licence / terms | Attribution |
|---|---|---|---|
| Eurostat, Comext DS-045409 (EU trade by HS/CN8) | `data/flows/*.parquet` (EU27 imports/exports by partner) | Reuse with attribution, Commission Decision 2011/833/EU | Source: Eurostat (DS-045409) |
| China Customs (GACC), exports by 8-digit HS code and destination (retrieved via FactIQ) | `data/flows/cn_exports.json` (annual tonnes; top destinations) | Official statistics; aggregates only, credited to GACC | Source: General Administration of Customs of China |
| Natural Earth (1:10m populated places; 1:110m land and borders) | `data/site_locations.csv` (town-centre fallback); `app/public/basemap.json` (offline basemap) | Public domain | Made with Natural Earth |
| Wikipedia (town articles) | `data/site_locations.csv`: town-centre coordinates for approximate placement | Coordinates are facts; source credited | Wikipedia contributors |

Separately licensed layers (not part of the ODbL database):

| Layer | Location | Licence |
|---|---|---|
| GEM Global Chemicals Inventory (base layer) | `external/gem/` (not yet ingested) | CC BY-NC-SA, Global Energy Monitor |

Basemap (app): © OpenStreetMap contributors (ODbL), tiles by OpenFreeMap.
