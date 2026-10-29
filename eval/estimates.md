# Estimate backtest

Built 2026-10-28 by `uv run portolan backtest`. Leave-one-out on the sourced (grade A–C) capacities of each molecule: hide one value, estimate it from the others, compare. A method is enabled for a molecule only if n ≥ 5 sourced values **and** at least 70% of the held-out estimates fall within 0.5–2× of the true value. Otherwise the field stays unknown.

`capacity_from_output` is not an imputation (it rescales the unit's own sourced output) and is shown as a range; no unit has both a sourced output and a sourced capacity yet, so it cannot be backtested. It never applies to by-products.

| Molecule | Method | n | Within 2× | Result |
|---|---|---:|---:|---|
| L-menthol | capacity_from_peers | 4 | 0/4 | disabled |
| alpha-pinene | capacity_from_peers | 2 | 0/0 | disabled |
| beta-ionone | capacity_from_peers | 0 | 0/0 | disabled |
| beta-pinene | capacity_from_peers | 2 | 0/0 | disabled |
| citral | capacity_from_peers | 4 | 0/4 | disabled |
| dihydromyrcenol | capacity_from_peers | 1 | 0/0 | disabled |
| geraniol | capacity_from_peers | 2 | 0/0 | disabled |
| isophytol | capacity_from_peers | 0 | 0/0 | disabled |
| isophytol | capacity_from_world_residual | 0 | 0/0 | disabled |
| isoprenol (3-methyl-3-buten-1-ol) | capacity_from_peers | 0 | 0/0 | disabled |
| linalool | capacity_from_peers | 2 | 0/0 | disabled |
| myrcene | capacity_from_peers | 1 | 0/0 | disabled |
| trimethylhydroquinone (TMHQ) | capacity_from_peers | 1 | 0/0 | disabled |
| vitamin A acetate | capacity_from_peers | 2 | 0/0 | disabled |
| vitamin E acetate (dl-alpha-tocopheryl acetate) | capacity_from_peers | 7 | 2/7 | disabled |

## Held-out values

**L-menthol · capacity_from_peers**

- unit:cn-bengbu-01:l-menthol: true 5,000 t/a, estimate 1,000 t/a (0.20×)
- unit:cn-yantai-01:l-menthol: true 1,000 t/a, estimate 3,000 t/a (3.00×)
- unit:cn-zhejiang-nhu-co-ltd-01:l-menthol: true 5,000 t/a, estimate 1,000 t/a (0.20×)
- unit:jp-iwata-01:l-menthol: true 3,000 t/a, estimate 1,000 t/a (0.33×)

**alpha-pinene · capacity_from_peers**

- unit:in-mahad-01:alpha-pinene: true 8,000 t/a, estimate none (too few peers)
- unit:se-sunpine-ab-01:alpha-pinene: true 1,150 t/a, estimate none (too few peers)

**beta-pinene · capacity_from_peers**

- unit:cn-suicheng-town-suixi-county-01:beta-pinene: true 4,000 t/a, estimate none (too few peers)
- unit:in-mahad-01:beta-pinene: true 2,600 t/a, estimate none (too few peers)

**citral · capacity_from_peers**

- unit:cn-weifang-01:citral: true 15,000 t/a, estimate 360 t/a (0.02×)
- unit:cn-yantai-01:citral: true 48,000 t/a, estimate 360 t/a (0.01×)
- unit:de-ludwigshafen-01:citral: true 40,000 t/a, estimate 360 t/a (0.01×)
- unit:in-mahad-01:citral: true 360 t/a, estimate 15,000 t/a (41.67×)

**dihydromyrcenol · capacity_from_peers**

- unit:in-rampur-01:dihydromyrcenol: true 6,000 t/a, estimate none (too few peers)

**geraniol · capacity_from_peers**

- unit:cn-weifang-01:geraniol: true 3,000 t/a, estimate none (too few peers)
- unit:cn-yantai-01:geraniol: true 10,000 t/a, estimate none (too few peers)

**linalool · capacity_from_peers**

- unit:cn-shanghai-petrochemical-co-ltd-01:linalool: true 2,500 t/a, estimate none (too few peers)
- unit:cn-weifang-01:linalool: true 5,000 t/a, estimate none (too few peers)

**myrcene · capacity_from_peers**

- unit:in-mahad-01:myrcene: true 4,800 t/a, estimate none (too few peers)

**trimethylhydroquinone (TMHQ) · capacity_from_peers**

- unit:cn-xingan-county-ji-an-01:trimethylhydroquinone-tmhq: true 3,000 t/a, estimate none (too few peers)

**vitamin A acetate · capacity_from_peers**

- unit:cn-zhejiang-nhu-co-ltd-01:vitamin-a-acetate: true 1,376 t/a, estimate none (too few peers)
- unit:de-ludwigshafen-01:vitamin-a-acetate: true 3,800 t/a, estimate none (too few peers)

**vitamin E acetate (dl-alpha-tocopheryl acetate) · capacity_from_peers**

- unit:ch-sisseln-01:vitamin-e-acetate-dl-alpha-tocopheryl-acetate: true 25,000 t/a, estimate 7,575 t/a (0.30×)
- unit:cn-dafeng-yancheng-01:vitamin-e-acetate-dl-alpha-tocopheryl-acetate: true 18,000 t/a, estimate 7,575 t/a (0.42×)
- unit:cn-jingzhou-01:vitamin-e-acetate-dl-alpha-tocopheryl-acetate: true 16,000 t/a, estimate 7,575 t/a (0.47×)
- unit:cn-weifang-01:vitamin-e-acetate-dl-alpha-tocopheryl-acetate: true 20,000 t/a, estimate 7,575 t/a (0.38×)
- unit:cn-zhejiang-nhu-co-ltd-01:vitamin-e-acetate-dl-alpha-tocopheryl-acetate: true 10,000 t/a, estimate 11,325 t/a (1.13×)
- unit:de-ludwigshafen-01:vitamin-e-acetate-dl-alpha-tocopheryl-acetate: true 15,000 t/a, estimate 7,575 t/a (0.51×)
- unit:in-usgaon-01:vitamin-e-acetate-dl-alpha-tocopheryl-acetate: true 300 t/a, estimate 13,750 t/a (45.83×)

