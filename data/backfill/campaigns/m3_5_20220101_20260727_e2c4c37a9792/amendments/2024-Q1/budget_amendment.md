# 2024-Q1 Partition Budget Amendment

Generated credential-free artifact — do not hand-edit.

- Campaign: `m3_5_20220101_20260727_e2c4c37a9792`
- Base campaign plan fingerprint: `b443f0910d40dfdb0f6986b17b76b582cc738c7c9f162d42317ef632c3759b9b`
- Amendment fingerprint: `95d0a475c79f38692641bb29c0bc93168b873e3056b4be37cef10c377ff6b9e8`
- Effective plan fingerprint: `29993c0a7718a2a39d67fab1eb865df4fb017b4e9d0890e46d55d88b23428ae4`
- Preserved predecessor: `m3_20240101_20240401_4aa59da8deab`
- Amended run: `m3_20240101_20240401_2c59812252db`
- Page-slot ceiling: `8` → `20`
- Hard ceiling for new HTTP attempts: `12`
- Authenticated requests made while planning: `0`

## Verified immutable prefix

| Sequence | Offset | Request hash | Response SHA-256 | Records |
| ---: | ---: | --- | --- | ---: |
| 1 | 0 | `f9e12568c2d7178b77200b2c1c1498337a0919a8e9500c2e67beb41d37d74b1a` | `97620ce703a96f4d5441b92adfd0d1940a04fffbc3c81e3ac572115bf8613f67` | 100 |
| 2 | 100 | `a27170f581d2b9e9fce4fbb544934e3e50bdbee9f1a590e5abfe15f9f8fe3659` | `55767332b49409129d9141fad66e2ed094bd94a7fd7830138d9851e1e6918bb7` | 100 |
| 3 | 200 | `1fd60dfaa9e991c5a53c1ee1e1b548da7779b7be848a64eed5999fbb24cf4977` | `b5d17cafce179d8bd6aa6285f7a14d1df8e44031c409ee457c4a215cee1ab4bf` | 100 |
| 4 | 300 | `268fee7ac477e77b79553109ab25aeeaafe4251e8be164978776d34e2455e54a` | `407362909722e42512813f2af916e5fe77acd95ed52675eb42e52b9e46ec94ca` | 100 |
| 5 | 400 | `3cb467f8d65bc344c675a9599d5df717be7f865fdbf3089b4854474df1fea50d` | `ab8a7135fe34faa0ac124c0b8ee722044693f8406d576a335e77071221f5f121` | 100 |
| 6 | 500 | `b574a7af1b7a82967a51220f7aea0493b46dfbba3c9cecf3971aab1505f3108c` | `95a21b0164f2f2fed4dfc8f69aa8ad32177ce3b1dd091f6c49a75ca62a2e1ce1` | 100 |
| 7 | 600 | `4178b85449866d8e111c282740059e4dcceed83b2ebae3e1261353aa295dbd55` | `158b4c0bbe85b4cccf7c3ff83b2c05be596f5f7a71da5c9856063bf1ed58e3c0` | 100 |
| 8 | 700 | `0aaa6401beda7eff4b54e513f73a84b8d903ecff8080aaf6ab9801cf89bc7ff1` | `91b61bbd141d3841af969b12af2623b4166d7c28ab140134311d317fe7e69220` | 100 |

## Conditional recovery requests

| Sequence | Offset | Request hash |
| ---: | ---: | --- |
| 9 | 800 | `c7aa370982768a22974e7ced7438bd7079e24f785f48a4a76f1a71a6eebc2b7a` |
| 10 | 900 | `28021996ccd458493d6c4611100488a0eb88bd9e1e54a814c0fe4cea74a8d284` |
| 11 | 1000 | `10b7c4293e05c5a03b6297acbe544ffbcf538c439ee26e83912a0080474cfc07` |
| 12 | 1100 | `bcb63899ace7fbdb005757cd7e980772ef271f4e1202d43a421886a41849567d` |
| 13 | 1200 | `aef3466e4e0dd7fc709dbf29900101e240bb77ad70c000bde5868d40017aed6b` |
| 14 | 1300 | `27ea74b9725cd22200f35cbf31e58a2374040a1d15f988cf224d3893c58b0a86` |
| 15 | 1400 | `19ba999550d6b20ce769ad78471cedd2f5e30c9fe91467fb706590017501cc09` |
| 16 | 1500 | `9c7897acab8b77dc413f5cfa4822d204d5ade4809c1d3b6798fdec627c76218d` |
| 17 | 1600 | `5ae3c150bf9d8e33b77f9b2df24a3c72e8342414736b59db4a37eaf19728d810` |
| 18 | 1700 | `80f55a31ae912a2ca07d13ef89074d566360a237ed63fe14ca7659bf13ce5a10` |
| 19 | 1800 | `8adbac5f97875c5c6a55a17e30827b075e9c350e8f0c5c0ed73330aef706db67` |
| 20 | 1900 | `289251a3b442f0452e78698d941fece552912f7e9021819690707e36956a7636` |

## Separately executable recovery command

```bash
.venv/bin/python scripts/plan_liquipedia_history_campaign.py --check-partition-readiness 2024-Q1 --include-approved-amendment 2024-Q1 && \
.venv/bin/python scripts/backfill_liquipedia_history.py \
  --start 2024-01-01T00:00:00Z \
  --end 2024-04-01T00:00:00Z \
  --tier 1 \
  --tier 2 \
  --page-size 100 \
  --max-requests 20 \
  --max-network-attempts 12 \
  --require-cache-prefix-pages 8 \
  --hourly-limit 54 \
  --request-interval-seconds 67 \
  --timeout-seconds 30 \
  --execute \
  --confirm-live-request-budget 12
```

## Chronological resume check after successful Q1 validation

```bash
.venv/bin/python scripts/plan_liquipedia_history_campaign.py --check-partition-readiness 2024-Q2 --include-approved-amendment 2024-Q1
```
