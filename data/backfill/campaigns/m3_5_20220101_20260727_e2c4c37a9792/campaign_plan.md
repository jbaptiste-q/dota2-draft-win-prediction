# Milestone 3.5 Historical Expansion Campaign Plan

Generated artifact — do not hand-edit.

- Campaign ID: `m3_5_20220101_20260727_e2c4c37a9792`
- Configuration fingerprint: `e2c4c37a9792cfa3e724d6bfee1173feb1c1ec880644ef43b159c73a2ca52774`
- Campaign plan fingerprint: `b443f0910d40dfdb0f6986b17b76b582cc738c7c9f162d42317ef632c3759b9b`
- Fixed range: `2022-01-01T00:00:00+00:00` inclusive to `2026-07-27T00:00:00+00:00` exclusive
- Authenticated requests made by planning: `0`

## Request Accounting

- Logical partitions: `19` (`18` new and `1` cached pilot)
- Conditional request specifications: `148` total, `144` for new partitions
- Maximum additional HTTP attempts: `100`
- Expected successful pages: `75–95`
- Pilot additional HTTP budget: `0`
- Automatic retries: `0`

## Ordered Partitions

| # | Partition | Kind | Start (inclusive) | End (exclusive) | Run ID | Slots | Campaign network budget |
| ---: | --- | --- | --- | --- | --- | ---: | ---: |
| 1 | `2022-Q1` | historical_quarter | `2022-01-01T00:00:00+00:00` | `2022-04-01T00:00:00+00:00` | `m3_20220101_20220401_36bbf248c8cf` | 8 | 8 |
| 2 | `2022-Q2` | historical_quarter | `2022-04-01T00:00:00+00:00` | `2022-07-01T00:00:00+00:00` | `m3_20220401_20220701_60f8944a646a` | 8 | 8 |
| 3 | `2022-Q3` | historical_quarter | `2022-07-01T00:00:00+00:00` | `2022-10-01T00:00:00+00:00` | `m3_20220701_20221001_19a8d74f1c5b` | 8 | 8 |
| 4 | `2022-Q4` | historical_quarter | `2022-10-01T00:00:00+00:00` | `2023-01-01T00:00:00+00:00` | `m3_20221001_20230101_ef93d0bbe56b` | 8 | 8 |
| 5 | `2023-Q1` | historical_quarter | `2023-01-01T00:00:00+00:00` | `2023-04-01T00:00:00+00:00` | `m3_20230101_20230401_f0eaf0202083` | 8 | 8 |
| 6 | `2023-Q2` | historical_quarter | `2023-04-01T00:00:00+00:00` | `2023-07-01T00:00:00+00:00` | `m3_20230401_20230701_5d5756ba4fd9` | 8 | 8 |
| 7 | `2023-Q3` | historical_quarter | `2023-07-01T00:00:00+00:00` | `2023-10-01T00:00:00+00:00` | `m3_20230701_20231001_3914e6822405` | 8 | 8 |
| 8 | `2023-Q4` | historical_quarter | `2023-10-01T00:00:00+00:00` | `2024-01-01T00:00:00+00:00` | `m3_20231001_20240101_5afa75ba56fa` | 8 | 8 |
| 9 | `2024-Q1` | historical_quarter | `2024-01-01T00:00:00+00:00` | `2024-04-01T00:00:00+00:00` | `m3_20240101_20240401_4aa59da8deab` | 8 | 8 |
| 10 | `2024-Q2` | historical_quarter | `2024-04-01T00:00:00+00:00` | `2024-07-01T00:00:00+00:00` | `m3_20240401_20240701_6575003bb769` | 8 | 8 |
| 11 | `2024-Q3` | historical_quarter | `2024-07-01T00:00:00+00:00` | `2024-10-01T00:00:00+00:00` | `m3_20240701_20241001_5bf5f710c335` | 8 | 8 |
| 12 | `2024-Q4` | historical_quarter | `2024-10-01T00:00:00+00:00` | `2025-01-01T00:00:00+00:00` | `m3_20241001_20250101_2c32e33d5a98` | 8 | 8 |
| 13 | `2025-Q1` | historical_quarter | `2025-01-01T00:00:00+00:00` | `2025-04-01T00:00:00+00:00` | `m3_20250101_20250401_cd59ec2f0029` | 8 | 8 |
| 14 | `2025-Q2` | historical_quarter | `2025-04-01T00:00:00+00:00` | `2025-07-01T00:00:00+00:00` | `m3_20250401_20250701_2c1023c34f35` | 8 | 8 |
| 15 | `2025-Q3` | historical_quarter | `2025-07-01T00:00:00+00:00` | `2025-10-01T00:00:00+00:00` | `m3_20250701_20251001_c63b3c6d9770` | 8 | 8 |
| 16 | `2025-Q4` | historical_quarter | `2025-10-01T00:00:00+00:00` | `2026-01-01T00:00:00+00:00` | `m3_20251001_20260101_e3f82e8aca4b` | 8 | 8 |
| 17 | `2026-Q1` | historical_quarter | `2026-01-01T00:00:00+00:00` | `2026-04-01T00:00:00+00:00` | `m3_20260101_20260401_a7d332ca2bbc` | 8 | 8 |
| 18 | `2026-Q2` | historical_quarter | `2026-04-01T00:00:00+00:00` | `2026-07-01T00:00:00+00:00` | `m3_20260401_20260701_452fe5854253` | 8 | 8 |
| 19 | `2026-07-pilot` | cached_pilot | `2026-07-01T00:00:00+00:00` | `2026-07-27T00:00:00+00:00` | `m3_20260701_20260727_0b40ae8811d6` | 4 | 0 |

## Exact Conditional Requests

### 2022-Q1

- Configuration hash: `36bbf248c8cfc2fe9c7505af9eabedcb2c39f31a9dbe7c424eb57e9b2257f477`
- Checkpoint: `data/backfill/runs/m3_20220101_20220401_36bbf248c8cf/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `a1d14b750bc61ccb403aa57ecb1276e0aeefffebfbbb9ee84435c810fafcf621` | `data/raw/liquipedia/backfill/cache/a1d14b750bc61ccb403aa57ecb1276e0aeefffebfbbb9ee84435c810fafcf621/response.json` |
| 2 | 100 | `6fdcd3580cd1eb1ad6ce121e1367036cb723de488f4d5d92bebded1e1ea6d36a` | `data/raw/liquipedia/backfill/cache/6fdcd3580cd1eb1ad6ce121e1367036cb723de488f4d5d92bebded1e1ea6d36a/response.json` |
| 3 | 200 | `7eec2a674958ad83cd0a7e6f1417d5c33f9b5e2619a138bd58f69aeb2d204381` | `data/raw/liquipedia/backfill/cache/7eec2a674958ad83cd0a7e6f1417d5c33f9b5e2619a138bd58f69aeb2d204381/response.json` |
| 4 | 300 | `67987592fcc87df00a8afcdc02698878fa4646c8f5bd90c0de9d05aa49875495` | `data/raw/liquipedia/backfill/cache/67987592fcc87df00a8afcdc02698878fa4646c8f5bd90c0de9d05aa49875495/response.json` |
| 5 | 400 | `9f559c7e03fa2d1471459f1903ec422eb466982160d2e247b1052b9ed37d6bce` | `data/raw/liquipedia/backfill/cache/9f559c7e03fa2d1471459f1903ec422eb466982160d2e247b1052b9ed37d6bce/response.json` |
| 6 | 500 | `20c240d58cca2db084ea90beae848160429a8fafcb7ae5ed9f3326457b313a5a` | `data/raw/liquipedia/backfill/cache/20c240d58cca2db084ea90beae848160429a8fafcb7ae5ed9f3326457b313a5a/response.json` |
| 7 | 600 | `3b4c3c53cbcc9ed84441daee250b961b2dd117abda1b95402f1507e3448b5d2f` | `data/raw/liquipedia/backfill/cache/3b4c3c53cbcc9ed84441daee250b961b2dd117abda1b95402f1507e3448b5d2f/response.json` |
| 8 | 700 | `394052143206af4d4136bc94db222da4dc05003ffb64c31a4f91e4edeeb20190` | `data/raw/liquipedia/backfill/cache/394052143206af4d4136bc94db222da4dc05003ffb64c31a4f91e4edeeb20190/response.json` |

### 2022-Q2

- Configuration hash: `60f8944a646a7a390039d9c4b69fa394aa1dca4d2a598ed7ee33f1c27ee283f3`
- Checkpoint: `data/backfill/runs/m3_20220401_20220701_60f8944a646a/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `ce50a58517c3a4a4516c58c18abda2c94677f2065b50e5c1a01e781977effad4` | `data/raw/liquipedia/backfill/cache/ce50a58517c3a4a4516c58c18abda2c94677f2065b50e5c1a01e781977effad4/response.json` |
| 2 | 100 | `c7f7393b6f598e94cabffff4ddd0ca9540bd711ffa8d1e369e9adb81187f2747` | `data/raw/liquipedia/backfill/cache/c7f7393b6f598e94cabffff4ddd0ca9540bd711ffa8d1e369e9adb81187f2747/response.json` |
| 3 | 200 | `a9fbc1f71766a70cc286af1455bf6bb078a8b949e1bbb918a5d31133c995c5b9` | `data/raw/liquipedia/backfill/cache/a9fbc1f71766a70cc286af1455bf6bb078a8b949e1bbb918a5d31133c995c5b9/response.json` |
| 4 | 300 | `5ac92ad060d6a97ce98fe5d82e5d0f4cd6339692021c6a1f56ec900fcf9abb7d` | `data/raw/liquipedia/backfill/cache/5ac92ad060d6a97ce98fe5d82e5d0f4cd6339692021c6a1f56ec900fcf9abb7d/response.json` |
| 5 | 400 | `da231c3bbc70495f46c4d25a1e52f382d3ab4cc72198bfa4f7d4193063556b39` | `data/raw/liquipedia/backfill/cache/da231c3bbc70495f46c4d25a1e52f382d3ab4cc72198bfa4f7d4193063556b39/response.json` |
| 6 | 500 | `ddb4f743eb2875d8aa588ff6feec4f0b736f4aa52a02905e0e7cfdb4d6515064` | `data/raw/liquipedia/backfill/cache/ddb4f743eb2875d8aa588ff6feec4f0b736f4aa52a02905e0e7cfdb4d6515064/response.json` |
| 7 | 600 | `6cc9e770703fb0680fed3b3ef7d4cc21a0c46b9cfccc0199d6672891288cfc56` | `data/raw/liquipedia/backfill/cache/6cc9e770703fb0680fed3b3ef7d4cc21a0c46b9cfccc0199d6672891288cfc56/response.json` |
| 8 | 700 | `c1da87fcb943f64d161be66f3814cb52e2a49243101491d4978f774dfa263a5c` | `data/raw/liquipedia/backfill/cache/c1da87fcb943f64d161be66f3814cb52e2a49243101491d4978f774dfa263a5c/response.json` |

### 2022-Q3

- Configuration hash: `19a8d74f1c5bed697445b546f3fdd6d27d2c677c53657ca1966840b6ed6ec0e2`
- Checkpoint: `data/backfill/runs/m3_20220701_20221001_19a8d74f1c5b/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `962625ea6f01ee8c68cd2620f9739f734d49ec560872bcea092f15cc50b92b83` | `data/raw/liquipedia/backfill/cache/962625ea6f01ee8c68cd2620f9739f734d49ec560872bcea092f15cc50b92b83/response.json` |
| 2 | 100 | `a97c986e319e8f26be1dc669f2e05d33e3d890d984385067502a94df2da81c47` | `data/raw/liquipedia/backfill/cache/a97c986e319e8f26be1dc669f2e05d33e3d890d984385067502a94df2da81c47/response.json` |
| 3 | 200 | `d2728b67d886e293e583f6f49c1c17e407834b597d0e3791e6a9cff2837afc8b` | `data/raw/liquipedia/backfill/cache/d2728b67d886e293e583f6f49c1c17e407834b597d0e3791e6a9cff2837afc8b/response.json` |
| 4 | 300 | `346a85125f8ee3a9ad457b272d97aa67a0b61edff314d2926abcc43daaf53c5d` | `data/raw/liquipedia/backfill/cache/346a85125f8ee3a9ad457b272d97aa67a0b61edff314d2926abcc43daaf53c5d/response.json` |
| 5 | 400 | `cfa9eab5bb38f5e748998387eb377594db8a8ef4a7618abc9553bdbc2c85708d` | `data/raw/liquipedia/backfill/cache/cfa9eab5bb38f5e748998387eb377594db8a8ef4a7618abc9553bdbc2c85708d/response.json` |
| 6 | 500 | `40f21e30ffd98913d37e8b9e6d56789c01d98c24e01151d112729fd1dc99fdc1` | `data/raw/liquipedia/backfill/cache/40f21e30ffd98913d37e8b9e6d56789c01d98c24e01151d112729fd1dc99fdc1/response.json` |
| 7 | 600 | `ec153887714f16b418ee00fe8b040b917d86bd756556a2cfc26551a677cfee0e` | `data/raw/liquipedia/backfill/cache/ec153887714f16b418ee00fe8b040b917d86bd756556a2cfc26551a677cfee0e/response.json` |
| 8 | 700 | `3e9a2a45efe38eaed6d1d699aa831850664c08e0808181f49c0c255055dbe7aa` | `data/raw/liquipedia/backfill/cache/3e9a2a45efe38eaed6d1d699aa831850664c08e0808181f49c0c255055dbe7aa/response.json` |

### 2022-Q4

- Configuration hash: `ef93d0bbe56b3acb38674e503541d1fc107f6405adaf22e589af05e1dd5829f6`
- Checkpoint: `data/backfill/runs/m3_20221001_20230101_ef93d0bbe56b/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `4c3ae7b0feedf0f73fe695b46bc4a666a290db1028a2af1ef6ab05b2ce5458d6` | `data/raw/liquipedia/backfill/cache/4c3ae7b0feedf0f73fe695b46bc4a666a290db1028a2af1ef6ab05b2ce5458d6/response.json` |
| 2 | 100 | `ff2068c37c02276b1eb081df22e0f3c3771233f118afc9d34daa885d9d645ca4` | `data/raw/liquipedia/backfill/cache/ff2068c37c02276b1eb081df22e0f3c3771233f118afc9d34daa885d9d645ca4/response.json` |
| 3 | 200 | `5147babce9417952b9b9497dcd1b1c9f8720c99b961feb7897da14f52508da9c` | `data/raw/liquipedia/backfill/cache/5147babce9417952b9b9497dcd1b1c9f8720c99b961feb7897da14f52508da9c/response.json` |
| 4 | 300 | `3a4a63fa061aa14aaee87c5935cb0c4476f5ca22e9cdd322de1340c74e4f0562` | `data/raw/liquipedia/backfill/cache/3a4a63fa061aa14aaee87c5935cb0c4476f5ca22e9cdd322de1340c74e4f0562/response.json` |
| 5 | 400 | `04e4425f019df03cd5974ebb9d99358d5208d7b7bcd033e054627db0732f6815` | `data/raw/liquipedia/backfill/cache/04e4425f019df03cd5974ebb9d99358d5208d7b7bcd033e054627db0732f6815/response.json` |
| 6 | 500 | `e73b44081e819ddef47022392cad209d6693432a8914d207e776350806f7cbae` | `data/raw/liquipedia/backfill/cache/e73b44081e819ddef47022392cad209d6693432a8914d207e776350806f7cbae/response.json` |
| 7 | 600 | `003d3c3d3f56c994e6f354015546749185f2975e611b1b9e232d6f65926d2440` | `data/raw/liquipedia/backfill/cache/003d3c3d3f56c994e6f354015546749185f2975e611b1b9e232d6f65926d2440/response.json` |
| 8 | 700 | `eae0a4ef3dc4b566faeab2b2b4aa0a4a9aae376e2cfa0d055be0cdd84db6ef8e` | `data/raw/liquipedia/backfill/cache/eae0a4ef3dc4b566faeab2b2b4aa0a4a9aae376e2cfa0d055be0cdd84db6ef8e/response.json` |

### 2023-Q1

- Configuration hash: `f0eaf02020834b358b061df339f92422bd66bc4d72671a838208978b7ca727a4`
- Checkpoint: `data/backfill/runs/m3_20230101_20230401_f0eaf0202083/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `8f751170a1ebb46ed3592c3a815593ea1c0227f0217f08e7df8221e84aa21324` | `data/raw/liquipedia/backfill/cache/8f751170a1ebb46ed3592c3a815593ea1c0227f0217f08e7df8221e84aa21324/response.json` |
| 2 | 100 | `6dc11346bc1667c14cec85e3360f6f05364d8211dcb09203475f3d0344c0f34b` | `data/raw/liquipedia/backfill/cache/6dc11346bc1667c14cec85e3360f6f05364d8211dcb09203475f3d0344c0f34b/response.json` |
| 3 | 200 | `72e3e34c3e15d0314cbc84e2950468b4072af8fc0df00fb7ea3a524044a4c2bd` | `data/raw/liquipedia/backfill/cache/72e3e34c3e15d0314cbc84e2950468b4072af8fc0df00fb7ea3a524044a4c2bd/response.json` |
| 4 | 300 | `3047ec485fdacb5e6563c51718b2c95cec60e0f2a3f93e66e2545f99160f67ac` | `data/raw/liquipedia/backfill/cache/3047ec485fdacb5e6563c51718b2c95cec60e0f2a3f93e66e2545f99160f67ac/response.json` |
| 5 | 400 | `ece1b107c7299decc8bfc161a77138ec5206a76ab5c90215bf962811f3034a28` | `data/raw/liquipedia/backfill/cache/ece1b107c7299decc8bfc161a77138ec5206a76ab5c90215bf962811f3034a28/response.json` |
| 6 | 500 | `9253d71683e5111d1370527b2939634ecf12f95dc48d78df8c75e772820bd855` | `data/raw/liquipedia/backfill/cache/9253d71683e5111d1370527b2939634ecf12f95dc48d78df8c75e772820bd855/response.json` |
| 7 | 600 | `ec50821db11cfe7b660e596a2de4d3b9905ed4c7ce452dc258413d10a56e82fc` | `data/raw/liquipedia/backfill/cache/ec50821db11cfe7b660e596a2de4d3b9905ed4c7ce452dc258413d10a56e82fc/response.json` |
| 8 | 700 | `7d7e6291df15aeaca83d30455600fb82de7451bfd89e17422fc9f11db6481819` | `data/raw/liquipedia/backfill/cache/7d7e6291df15aeaca83d30455600fb82de7451bfd89e17422fc9f11db6481819/response.json` |

### 2023-Q2

- Configuration hash: `5d5756ba4fd9df0fd6a610c37bbe67691aea6a35c5c0b339891ac0533b9f1d89`
- Checkpoint: `data/backfill/runs/m3_20230401_20230701_5d5756ba4fd9/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `e3f3a5288f7eb7175ecd8affa92797de9097cd280f72ee9b34b0a9303055e285` | `data/raw/liquipedia/backfill/cache/e3f3a5288f7eb7175ecd8affa92797de9097cd280f72ee9b34b0a9303055e285/response.json` |
| 2 | 100 | `8056aa746318018b57bf3a1e561550660ac298deab68caff33bb0e1174d34d59` | `data/raw/liquipedia/backfill/cache/8056aa746318018b57bf3a1e561550660ac298deab68caff33bb0e1174d34d59/response.json` |
| 3 | 200 | `2bb441f61185269de15fd6a80da1638b83dc0422a3b41e50a98b133e9d6f3351` | `data/raw/liquipedia/backfill/cache/2bb441f61185269de15fd6a80da1638b83dc0422a3b41e50a98b133e9d6f3351/response.json` |
| 4 | 300 | `de2b7d128dcb95a21d03a9e6cc38468f463309522ea2b0218357c18449fb1ddc` | `data/raw/liquipedia/backfill/cache/de2b7d128dcb95a21d03a9e6cc38468f463309522ea2b0218357c18449fb1ddc/response.json` |
| 5 | 400 | `5e05eda950411584daf9de9fcafe838b10ea8b690f9d382d5012db5f6ab028d4` | `data/raw/liquipedia/backfill/cache/5e05eda950411584daf9de9fcafe838b10ea8b690f9d382d5012db5f6ab028d4/response.json` |
| 6 | 500 | `56e9d4bb04c46ab3e5058a236e9b9b9b588a6338e0c7578f12ef1e83d72d465e` | `data/raw/liquipedia/backfill/cache/56e9d4bb04c46ab3e5058a236e9b9b9b588a6338e0c7578f12ef1e83d72d465e/response.json` |
| 7 | 600 | `24d92937b16d1fcf7958949fd82b4b64eb7f9ef320cd804d34c199956fb5daa4` | `data/raw/liquipedia/backfill/cache/24d92937b16d1fcf7958949fd82b4b64eb7f9ef320cd804d34c199956fb5daa4/response.json` |
| 8 | 700 | `37532c929bf90747366a0e4720e0c1572c991ff34ae3ff38612bc513df3c9de0` | `data/raw/liquipedia/backfill/cache/37532c929bf90747366a0e4720e0c1572c991ff34ae3ff38612bc513df3c9de0/response.json` |

### 2023-Q3

- Configuration hash: `3914e6822405be757288e5fcf1c01ea374c4f7cead9abcad888e76f757e2b6cc`
- Checkpoint: `data/backfill/runs/m3_20230701_20231001_3914e6822405/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `e80f66d8ea2fbaadfe0e87ed575d793c3c930255aeb83ada8afef030669680c1` | `data/raw/liquipedia/backfill/cache/e80f66d8ea2fbaadfe0e87ed575d793c3c930255aeb83ada8afef030669680c1/response.json` |
| 2 | 100 | `4b8c1fcc5f718934fd5ae98fb198fe04993ca4ed07180c72b098664babe1050b` | `data/raw/liquipedia/backfill/cache/4b8c1fcc5f718934fd5ae98fb198fe04993ca4ed07180c72b098664babe1050b/response.json` |
| 3 | 200 | `8f1651486fcf7666394332e97be416da436030d2055165e142ada28c57768513` | `data/raw/liquipedia/backfill/cache/8f1651486fcf7666394332e97be416da436030d2055165e142ada28c57768513/response.json` |
| 4 | 300 | `fe7df22ad9112dedeef8958e1d310e40146b976775e68e1ec3f3ea462229c9d0` | `data/raw/liquipedia/backfill/cache/fe7df22ad9112dedeef8958e1d310e40146b976775e68e1ec3f3ea462229c9d0/response.json` |
| 5 | 400 | `57948f4edd07f0f4afa0cb8861da7e1927f1d08dadd1bd10be5c9929a583dd8b` | `data/raw/liquipedia/backfill/cache/57948f4edd07f0f4afa0cb8861da7e1927f1d08dadd1bd10be5c9929a583dd8b/response.json` |
| 6 | 500 | `31c76f9baf0643d4cf440cf35b4625843ac3700b7b5bc76e9be56d9272b64c77` | `data/raw/liquipedia/backfill/cache/31c76f9baf0643d4cf440cf35b4625843ac3700b7b5bc76e9be56d9272b64c77/response.json` |
| 7 | 600 | `7a38a0622fd2187c79b9c68f385e535f741137ae86254fd27b62e4cf94eba002` | `data/raw/liquipedia/backfill/cache/7a38a0622fd2187c79b9c68f385e535f741137ae86254fd27b62e4cf94eba002/response.json` |
| 8 | 700 | `6e96b1c7ab9a5bc19f81146a28616f66c50b6090fd9a8d90649c5c8c4a85d583` | `data/raw/liquipedia/backfill/cache/6e96b1c7ab9a5bc19f81146a28616f66c50b6090fd9a8d90649c5c8c4a85d583/response.json` |

### 2023-Q4

- Configuration hash: `5afa75ba56fa1a6a6ea4b7dc1692795dadb9a82d21d365fdd2c921b4e42e1069`
- Checkpoint: `data/backfill/runs/m3_20231001_20240101_5afa75ba56fa/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `620c183faec4c770c8ce4a43c34c4f78ce99ed7dde8f426c149cfa52fbf45e0b` | `data/raw/liquipedia/backfill/cache/620c183faec4c770c8ce4a43c34c4f78ce99ed7dde8f426c149cfa52fbf45e0b/response.json` |
| 2 | 100 | `b2a1406bffc187f853d199c77d90258c56e818af95d83b1cbd09fcaa71dd5418` | `data/raw/liquipedia/backfill/cache/b2a1406bffc187f853d199c77d90258c56e818af95d83b1cbd09fcaa71dd5418/response.json` |
| 3 | 200 | `c70ac98222eba2ca5004c5f193b223064b6671ba4bb9be88c00c0499dd05e62a` | `data/raw/liquipedia/backfill/cache/c70ac98222eba2ca5004c5f193b223064b6671ba4bb9be88c00c0499dd05e62a/response.json` |
| 4 | 300 | `c064c66c2be6cc153bd707113d3e9c7474952d7fa98b71f462b8e73db66f8827` | `data/raw/liquipedia/backfill/cache/c064c66c2be6cc153bd707113d3e9c7474952d7fa98b71f462b8e73db66f8827/response.json` |
| 5 | 400 | `66e023e5b2e7e8c289f72b65abc91f12abba6e8b9f7031b35c5cd1428ec80ee3` | `data/raw/liquipedia/backfill/cache/66e023e5b2e7e8c289f72b65abc91f12abba6e8b9f7031b35c5cd1428ec80ee3/response.json` |
| 6 | 500 | `9cd7de659fa516f6146ff536b4f8f73fad569d252747fee752dc3816fe774f81` | `data/raw/liquipedia/backfill/cache/9cd7de659fa516f6146ff536b4f8f73fad569d252747fee752dc3816fe774f81/response.json` |
| 7 | 600 | `a86f8adf65c4beb96ce31a3fba167f6702e8ac96629c95ef14f946f169972402` | `data/raw/liquipedia/backfill/cache/a86f8adf65c4beb96ce31a3fba167f6702e8ac96629c95ef14f946f169972402/response.json` |
| 8 | 700 | `934f7685ddcc8fe859399e2b666195e67cff145362f5dc13813d68e3aee31f5a` | `data/raw/liquipedia/backfill/cache/934f7685ddcc8fe859399e2b666195e67cff145362f5dc13813d68e3aee31f5a/response.json` |

### 2024-Q1

- Configuration hash: `4aa59da8deab0748102a63a09c21d1b9bc10dfeb317bf57b7633d2ea0014a051`
- Checkpoint: `data/backfill/runs/m3_20240101_20240401_4aa59da8deab/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `f9e12568c2d7178b77200b2c1c1498337a0919a8e9500c2e67beb41d37d74b1a` | `data/raw/liquipedia/backfill/cache/f9e12568c2d7178b77200b2c1c1498337a0919a8e9500c2e67beb41d37d74b1a/response.json` |
| 2 | 100 | `a27170f581d2b9e9fce4fbb544934e3e50bdbee9f1a590e5abfe15f9f8fe3659` | `data/raw/liquipedia/backfill/cache/a27170f581d2b9e9fce4fbb544934e3e50bdbee9f1a590e5abfe15f9f8fe3659/response.json` |
| 3 | 200 | `1fd60dfaa9e991c5a53c1ee1e1b548da7779b7be848a64eed5999fbb24cf4977` | `data/raw/liquipedia/backfill/cache/1fd60dfaa9e991c5a53c1ee1e1b548da7779b7be848a64eed5999fbb24cf4977/response.json` |
| 4 | 300 | `268fee7ac477e77b79553109ab25aeeaafe4251e8be164978776d34e2455e54a` | `data/raw/liquipedia/backfill/cache/268fee7ac477e77b79553109ab25aeeaafe4251e8be164978776d34e2455e54a/response.json` |
| 5 | 400 | `3cb467f8d65bc344c675a9599d5df717be7f865fdbf3089b4854474df1fea50d` | `data/raw/liquipedia/backfill/cache/3cb467f8d65bc344c675a9599d5df717be7f865fdbf3089b4854474df1fea50d/response.json` |
| 6 | 500 | `b574a7af1b7a82967a51220f7aea0493b46dfbba3c9cecf3971aab1505f3108c` | `data/raw/liquipedia/backfill/cache/b574a7af1b7a82967a51220f7aea0493b46dfbba3c9cecf3971aab1505f3108c/response.json` |
| 7 | 600 | `4178b85449866d8e111c282740059e4dcceed83b2ebae3e1261353aa295dbd55` | `data/raw/liquipedia/backfill/cache/4178b85449866d8e111c282740059e4dcceed83b2ebae3e1261353aa295dbd55/response.json` |
| 8 | 700 | `0aaa6401beda7eff4b54e513f73a84b8d903ecff8080aaf6ab9801cf89bc7ff1` | `data/raw/liquipedia/backfill/cache/0aaa6401beda7eff4b54e513f73a84b8d903ecff8080aaf6ab9801cf89bc7ff1/response.json` |

### 2024-Q2

- Configuration hash: `6575003bb7696a42a2ceb6f0a09ff0e6f4d81267a578912b64fdbe6cc9e45bad`
- Checkpoint: `data/backfill/runs/m3_20240401_20240701_6575003bb769/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `194ddb609388dcf6219e04f4842fadf6bc142baf1b78d6b383e83089a28c1209` | `data/raw/liquipedia/backfill/cache/194ddb609388dcf6219e04f4842fadf6bc142baf1b78d6b383e83089a28c1209/response.json` |
| 2 | 100 | `c729b8ce8d6b6c7b5b117448e54491ab68f1a385f1bbf6a250f1d32f6269f1c7` | `data/raw/liquipedia/backfill/cache/c729b8ce8d6b6c7b5b117448e54491ab68f1a385f1bbf6a250f1d32f6269f1c7/response.json` |
| 3 | 200 | `b9987c19596c9fe3d3c515c99820589f84dc61f764a14f3c0a676d37a3465a75` | `data/raw/liquipedia/backfill/cache/b9987c19596c9fe3d3c515c99820589f84dc61f764a14f3c0a676d37a3465a75/response.json` |
| 4 | 300 | `ca1daec2550d4d2563aaf8ade9257131f59c9d36c359f82d82d436eb0d769768` | `data/raw/liquipedia/backfill/cache/ca1daec2550d4d2563aaf8ade9257131f59c9d36c359f82d82d436eb0d769768/response.json` |
| 5 | 400 | `d8380e285af7f20df198837c7617d78069b9018c9b66a32607bee27b0ecc6737` | `data/raw/liquipedia/backfill/cache/d8380e285af7f20df198837c7617d78069b9018c9b66a32607bee27b0ecc6737/response.json` |
| 6 | 500 | `0c23def1ba711d300eb9bfe714b85bd89df4ea11bd08b329d4948f31dc92990d` | `data/raw/liquipedia/backfill/cache/0c23def1ba711d300eb9bfe714b85bd89df4ea11bd08b329d4948f31dc92990d/response.json` |
| 7 | 600 | `cbaca58aa1d1bf6ab1a271e77fa5093074383420c1e445cd604f0431b8f1fa36` | `data/raw/liquipedia/backfill/cache/cbaca58aa1d1bf6ab1a271e77fa5093074383420c1e445cd604f0431b8f1fa36/response.json` |
| 8 | 700 | `4715ae36a9d16d9439b1d2b9f37bc1987feca2e6dac5287cfd8a5d3d253a7049` | `data/raw/liquipedia/backfill/cache/4715ae36a9d16d9439b1d2b9f37bc1987feca2e6dac5287cfd8a5d3d253a7049/response.json` |

### 2024-Q3

- Configuration hash: `5bf5f710c335fa9226d613938d53b124db710f820f0ae2445ae68cb1f6df8a88`
- Checkpoint: `data/backfill/runs/m3_20240701_20241001_5bf5f710c335/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `44e7cb52592624b6b0290b549c4cbac99e0cb2ab81d155f71b5d78eb0b89d455` | `data/raw/liquipedia/backfill/cache/44e7cb52592624b6b0290b549c4cbac99e0cb2ab81d155f71b5d78eb0b89d455/response.json` |
| 2 | 100 | `de021289ce2d705b75f389093c47368f29dc6352863f5c6407fc84d8358eac4b` | `data/raw/liquipedia/backfill/cache/de021289ce2d705b75f389093c47368f29dc6352863f5c6407fc84d8358eac4b/response.json` |
| 3 | 200 | `fc5cbd47aed283764cd277848ae83ba967dc6bd9753559c26fb259a3a916d41b` | `data/raw/liquipedia/backfill/cache/fc5cbd47aed283764cd277848ae83ba967dc6bd9753559c26fb259a3a916d41b/response.json` |
| 4 | 300 | `a86898e4c3cfab254dcea220dc6c6286a76523cc8074e14921b422a2b32e5679` | `data/raw/liquipedia/backfill/cache/a86898e4c3cfab254dcea220dc6c6286a76523cc8074e14921b422a2b32e5679/response.json` |
| 5 | 400 | `b537ab55ef2084bbe7e076b627e8fce5bc08ac8a70b3d0336f591729769cdbb8` | `data/raw/liquipedia/backfill/cache/b537ab55ef2084bbe7e076b627e8fce5bc08ac8a70b3d0336f591729769cdbb8/response.json` |
| 6 | 500 | `d52d0bd9e64d06e164fda2925cdcf1d5b0544a99176a864706495fa42bf79007` | `data/raw/liquipedia/backfill/cache/d52d0bd9e64d06e164fda2925cdcf1d5b0544a99176a864706495fa42bf79007/response.json` |
| 7 | 600 | `cf2e04e739238e2964ff811f42c136b632484676e87be7b789119ea4536d761d` | `data/raw/liquipedia/backfill/cache/cf2e04e739238e2964ff811f42c136b632484676e87be7b789119ea4536d761d/response.json` |
| 8 | 700 | `e838685cd67b037cb56f34610d2a9b93f48fdc57b240528caf01a3cd01366f25` | `data/raw/liquipedia/backfill/cache/e838685cd67b037cb56f34610d2a9b93f48fdc57b240528caf01a3cd01366f25/response.json` |

### 2024-Q4

- Configuration hash: `2c32e33d5a9875e31c66c100266c725982306812b6f7397f8c854c8eba3eb64d`
- Checkpoint: `data/backfill/runs/m3_20241001_20250101_2c32e33d5a98/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `f69c87806025cfccb8e371d492e532803351403761d0017b09cf4a374fa625ef` | `data/raw/liquipedia/backfill/cache/f69c87806025cfccb8e371d492e532803351403761d0017b09cf4a374fa625ef/response.json` |
| 2 | 100 | `1c9753fd975db01b6857eea4a25571628789f097d28a8c900603e0b7deada43b` | `data/raw/liquipedia/backfill/cache/1c9753fd975db01b6857eea4a25571628789f097d28a8c900603e0b7deada43b/response.json` |
| 3 | 200 | `92f9bf94e1bba1c431cad5162af8095186ab6836df2a2e3d284312b0347dbc07` | `data/raw/liquipedia/backfill/cache/92f9bf94e1bba1c431cad5162af8095186ab6836df2a2e3d284312b0347dbc07/response.json` |
| 4 | 300 | `a03b61962fd1efe5a1ad2b988f71c78dfbe5d3019b113b466536bb3c3853e656` | `data/raw/liquipedia/backfill/cache/a03b61962fd1efe5a1ad2b988f71c78dfbe5d3019b113b466536bb3c3853e656/response.json` |
| 5 | 400 | `e689a7de871ad57e6c0ffa707e6f04a11716c04c3ae901283349bab5e601a50d` | `data/raw/liquipedia/backfill/cache/e689a7de871ad57e6c0ffa707e6f04a11716c04c3ae901283349bab5e601a50d/response.json` |
| 6 | 500 | `66f0884c265584e2c9ff0e952094c8f6c83dd108275aa8acd22687345109a72d` | `data/raw/liquipedia/backfill/cache/66f0884c265584e2c9ff0e952094c8f6c83dd108275aa8acd22687345109a72d/response.json` |
| 7 | 600 | `0558ee5972aefe75fc90008eb17e1db9386cf2a70899a3071dacf48afa21d484` | `data/raw/liquipedia/backfill/cache/0558ee5972aefe75fc90008eb17e1db9386cf2a70899a3071dacf48afa21d484/response.json` |
| 8 | 700 | `ff89f43f7bceac8fa3fe24ee937d18c20ab7d6b3c5dd149db860c25e9c4d01c7` | `data/raw/liquipedia/backfill/cache/ff89f43f7bceac8fa3fe24ee937d18c20ab7d6b3c5dd149db860c25e9c4d01c7/response.json` |

### 2025-Q1

- Configuration hash: `cd59ec2f00299e5b02ef9fd756039b01968dfadc418abfee9fc9140cfa8a5660`
- Checkpoint: `data/backfill/runs/m3_20250101_20250401_cd59ec2f0029/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `039c300c08a4c45c01bbbec86e40d7970d08fc834de9270b1d3b6be588952a1f` | `data/raw/liquipedia/backfill/cache/039c300c08a4c45c01bbbec86e40d7970d08fc834de9270b1d3b6be588952a1f/response.json` |
| 2 | 100 | `4d3c44fe16ece2766565444ae034f01c291f2e3732c679f2982a63b2e703cb87` | `data/raw/liquipedia/backfill/cache/4d3c44fe16ece2766565444ae034f01c291f2e3732c679f2982a63b2e703cb87/response.json` |
| 3 | 200 | `8d7daa8935ffd60c26f61703cde7fa9318867a1f785c00e2e768417ed44f5cd5` | `data/raw/liquipedia/backfill/cache/8d7daa8935ffd60c26f61703cde7fa9318867a1f785c00e2e768417ed44f5cd5/response.json` |
| 4 | 300 | `e8244b861e22ed035ce5520af98af007a7f8a754ff94f8ab474042e9b6af52f3` | `data/raw/liquipedia/backfill/cache/e8244b861e22ed035ce5520af98af007a7f8a754ff94f8ab474042e9b6af52f3/response.json` |
| 5 | 400 | `1e807b7bfb48c58bed5a427f2cb3d33bc7b7ce4a7adf07ede64f8d9e718d3690` | `data/raw/liquipedia/backfill/cache/1e807b7bfb48c58bed5a427f2cb3d33bc7b7ce4a7adf07ede64f8d9e718d3690/response.json` |
| 6 | 500 | `3f02bd335e51705263b8d8eddea8a4a154d59592d3d5e8d9eee1042fa1fd5709` | `data/raw/liquipedia/backfill/cache/3f02bd335e51705263b8d8eddea8a4a154d59592d3d5e8d9eee1042fa1fd5709/response.json` |
| 7 | 600 | `03304ef179150737acc18cb23ae7159ddfc6ac2edaaa67b6af219af0d64526d7` | `data/raw/liquipedia/backfill/cache/03304ef179150737acc18cb23ae7159ddfc6ac2edaaa67b6af219af0d64526d7/response.json` |
| 8 | 700 | `90299c4714235ccc88a3f20fcf5cc9172ae328e9a9deb34f92f57e83a5e159d0` | `data/raw/liquipedia/backfill/cache/90299c4714235ccc88a3f20fcf5cc9172ae328e9a9deb34f92f57e83a5e159d0/response.json` |

### 2025-Q2

- Configuration hash: `2c1023c34f355e7a85f4292abaa6d98c349c2d7dc0b8fb59dc0fbad25a21fa0b`
- Checkpoint: `data/backfill/runs/m3_20250401_20250701_2c1023c34f35/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `7b6a70484e6d5a6946907dc0aa401b7e25ed1908366ff506f06e2868cc4e5dc6` | `data/raw/liquipedia/backfill/cache/7b6a70484e6d5a6946907dc0aa401b7e25ed1908366ff506f06e2868cc4e5dc6/response.json` |
| 2 | 100 | `6d836a9e5d18dfed172acab3b3fd671ba6e398c1a5d922a84bf111c8537ed775` | `data/raw/liquipedia/backfill/cache/6d836a9e5d18dfed172acab3b3fd671ba6e398c1a5d922a84bf111c8537ed775/response.json` |
| 3 | 200 | `4366676c04b636c58d5c472c408afc71af4344df7d6a0887061235d00e847b74` | `data/raw/liquipedia/backfill/cache/4366676c04b636c58d5c472c408afc71af4344df7d6a0887061235d00e847b74/response.json` |
| 4 | 300 | `93c8b4cf2faac34ea66bffbe5702764f6e7bfe977208dc3bcd06555cdd5cd8de` | `data/raw/liquipedia/backfill/cache/93c8b4cf2faac34ea66bffbe5702764f6e7bfe977208dc3bcd06555cdd5cd8de/response.json` |
| 5 | 400 | `8ae4cfe74c6161eab8fd0c747738ba48ad36d108564ea4937dcd50ac618f6aca` | `data/raw/liquipedia/backfill/cache/8ae4cfe74c6161eab8fd0c747738ba48ad36d108564ea4937dcd50ac618f6aca/response.json` |
| 6 | 500 | `729c981741efea2ff8a0aa360ab55db7be58758cbfe24fda9a46ad9a4387f551` | `data/raw/liquipedia/backfill/cache/729c981741efea2ff8a0aa360ab55db7be58758cbfe24fda9a46ad9a4387f551/response.json` |
| 7 | 600 | `8bc6b0bf7755dd1cc4b178d329ddfb6f34cb142168a80d1eedc2dba73e6bca22` | `data/raw/liquipedia/backfill/cache/8bc6b0bf7755dd1cc4b178d329ddfb6f34cb142168a80d1eedc2dba73e6bca22/response.json` |
| 8 | 700 | `0ed7538521365a0c1371e5ed1148289d8bfabee4b2f64959640fe9e3803d067a` | `data/raw/liquipedia/backfill/cache/0ed7538521365a0c1371e5ed1148289d8bfabee4b2f64959640fe9e3803d067a/response.json` |

### 2025-Q3

- Configuration hash: `c63b3c6d9770fbbc8ed1ff548ef7492a5db10106e5a2bcfdef5298aa4d0bad2c`
- Checkpoint: `data/backfill/runs/m3_20250701_20251001_c63b3c6d9770/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `d7604a13a0abe3f69acc799689516d2a533dbbdd8be323b920e16b408b6f00ef` | `data/raw/liquipedia/backfill/cache/d7604a13a0abe3f69acc799689516d2a533dbbdd8be323b920e16b408b6f00ef/response.json` |
| 2 | 100 | `c90546a61d83fb4b66a0abe0087ea9b5c077a6586526ca83ded634e783f2a454` | `data/raw/liquipedia/backfill/cache/c90546a61d83fb4b66a0abe0087ea9b5c077a6586526ca83ded634e783f2a454/response.json` |
| 3 | 200 | `c062aa34559e126d90ce7515117adfdf6b747a1344c3c76886bc4d815e03b432` | `data/raw/liquipedia/backfill/cache/c062aa34559e126d90ce7515117adfdf6b747a1344c3c76886bc4d815e03b432/response.json` |
| 4 | 300 | `c9e8048fc3e31883a9bb422d9a77535fcd80f632939181b94399ca70ecd45b00` | `data/raw/liquipedia/backfill/cache/c9e8048fc3e31883a9bb422d9a77535fcd80f632939181b94399ca70ecd45b00/response.json` |
| 5 | 400 | `5e1ba489d20ab14d01e678404c4ad26af856214978a8c9d01cd2492b08b92c80` | `data/raw/liquipedia/backfill/cache/5e1ba489d20ab14d01e678404c4ad26af856214978a8c9d01cd2492b08b92c80/response.json` |
| 6 | 500 | `0829d69662f12e59fb5caa77313702589f4458ca8b3e09ec710305ed86640ecb` | `data/raw/liquipedia/backfill/cache/0829d69662f12e59fb5caa77313702589f4458ca8b3e09ec710305ed86640ecb/response.json` |
| 7 | 600 | `52ecebedcdd60abd5982e1261ab26463b83539e8a0bb01cdb785e398dc84c425` | `data/raw/liquipedia/backfill/cache/52ecebedcdd60abd5982e1261ab26463b83539e8a0bb01cdb785e398dc84c425/response.json` |
| 8 | 700 | `6a8950f55ad7bee7ea8c2ce362d2e4708074b5b0961a089464a3ba306fc490f4` | `data/raw/liquipedia/backfill/cache/6a8950f55ad7bee7ea8c2ce362d2e4708074b5b0961a089464a3ba306fc490f4/response.json` |

### 2025-Q4

- Configuration hash: `e3f82e8aca4bbbe2e639c633497e16d298cde6719d964cc6be27632157bdc2de`
- Checkpoint: `data/backfill/runs/m3_20251001_20260101_e3f82e8aca4b/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `45eaa40df386d91e6c062ee582167435c760516594f488882eccc9c08c664000` | `data/raw/liquipedia/backfill/cache/45eaa40df386d91e6c062ee582167435c760516594f488882eccc9c08c664000/response.json` |
| 2 | 100 | `ceb98e98298fae6b4292b9ed82a7fded1a0db7e3baad1c49ea74955631ecd58b` | `data/raw/liquipedia/backfill/cache/ceb98e98298fae6b4292b9ed82a7fded1a0db7e3baad1c49ea74955631ecd58b/response.json` |
| 3 | 200 | `2b7d69bd23b2017e0a7bdf9563f5b1da0658034b3ed41502d876c87a1979f5f8` | `data/raw/liquipedia/backfill/cache/2b7d69bd23b2017e0a7bdf9563f5b1da0658034b3ed41502d876c87a1979f5f8/response.json` |
| 4 | 300 | `4762accad0553cde0ec41952a40cc016a59d5768ae19abeb5775fb18106f84d4` | `data/raw/liquipedia/backfill/cache/4762accad0553cde0ec41952a40cc016a59d5768ae19abeb5775fb18106f84d4/response.json` |
| 5 | 400 | `2d023b9f311e067e1ffdce37aa4c53fa8aab2c7231e89b75a53612cc20f8cd81` | `data/raw/liquipedia/backfill/cache/2d023b9f311e067e1ffdce37aa4c53fa8aab2c7231e89b75a53612cc20f8cd81/response.json` |
| 6 | 500 | `bc8f5f59a7bcb3b2f6c359a11a66a50425ff9c854d955bd3fd130e2d3cd86a52` | `data/raw/liquipedia/backfill/cache/bc8f5f59a7bcb3b2f6c359a11a66a50425ff9c854d955bd3fd130e2d3cd86a52/response.json` |
| 7 | 600 | `bbdcf4d5d4caf32477a58a0c15e3d19de3c4cadf182371f075485438f7649e21` | `data/raw/liquipedia/backfill/cache/bbdcf4d5d4caf32477a58a0c15e3d19de3c4cadf182371f075485438f7649e21/response.json` |
| 8 | 700 | `2920717b6a109864adf693995803bfc63c2e13ea9e7df7bff7b6898ea25c4e57` | `data/raw/liquipedia/backfill/cache/2920717b6a109864adf693995803bfc63c2e13ea9e7df7bff7b6898ea25c4e57/response.json` |

### 2026-Q1

- Configuration hash: `a7d332ca2bbc68e65243408ae350a2e48b055e0a5f7ad2ab9994cd1aef9a54b9`
- Checkpoint: `data/backfill/runs/m3_20260101_20260401_a7d332ca2bbc/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `59c9d7677e1df2b4b3fb761e1f3d5d270c45e8c9ece95dede6da641c4be6c89b` | `data/raw/liquipedia/backfill/cache/59c9d7677e1df2b4b3fb761e1f3d5d270c45e8c9ece95dede6da641c4be6c89b/response.json` |
| 2 | 100 | `ba0dfc4cf052988c69fd9de6133837c592b69eba1eefa6c478d61d285d36723c` | `data/raw/liquipedia/backfill/cache/ba0dfc4cf052988c69fd9de6133837c592b69eba1eefa6c478d61d285d36723c/response.json` |
| 3 | 200 | `f2635475904e97a5b9cde46526c26e5b7524b8bb0436c703f7c2d6e7a86bde24` | `data/raw/liquipedia/backfill/cache/f2635475904e97a5b9cde46526c26e5b7524b8bb0436c703f7c2d6e7a86bde24/response.json` |
| 4 | 300 | `e4b5c6336d7de454556aa225499ed02c4b3958fdcf0b699edecc8fbdf438ad3d` | `data/raw/liquipedia/backfill/cache/e4b5c6336d7de454556aa225499ed02c4b3958fdcf0b699edecc8fbdf438ad3d/response.json` |
| 5 | 400 | `87e17733e277754bdb84f594275009bb1aca498ec7324b456aa6fa833ad29a0a` | `data/raw/liquipedia/backfill/cache/87e17733e277754bdb84f594275009bb1aca498ec7324b456aa6fa833ad29a0a/response.json` |
| 6 | 500 | `46fdc928842cfc589bc31ccd8a5f37cf491f5d515247230f9372cb2c59d3715d` | `data/raw/liquipedia/backfill/cache/46fdc928842cfc589bc31ccd8a5f37cf491f5d515247230f9372cb2c59d3715d/response.json` |
| 7 | 600 | `4625c0c87a28a9c01b63d59df2a1b06a69f7d39ed6854af10a736dd3cb145bbe` | `data/raw/liquipedia/backfill/cache/4625c0c87a28a9c01b63d59df2a1b06a69f7d39ed6854af10a736dd3cb145bbe/response.json` |
| 8 | 700 | `b36b76fd3dc5450c8e6672bef12ca37b8698639b458179e975a163afa1949659` | `data/raw/liquipedia/backfill/cache/b36b76fd3dc5450c8e6672bef12ca37b8698639b458179e975a163afa1949659/response.json` |

### 2026-Q2

- Configuration hash: `452fe5854253ea5176458199a10f3ff4e442d6be7110cd0ccc7ee971f7ce06fa`
- Checkpoint: `data/backfill/runs/m3_20260401_20260701_452fe5854253/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `separate_explicit_live_approval_required`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `0ca682712292f51b2007b0d6be7747bd50a3be1c0729cb4f3a369efdeedca8b8` | `data/raw/liquipedia/backfill/cache/0ca682712292f51b2007b0d6be7747bd50a3be1c0729cb4f3a369efdeedca8b8/response.json` |
| 2 | 100 | `92cd6bdba03415b751077df6b29ba46558d6ad5c9fe698ada8025b5deac2a9b6` | `data/raw/liquipedia/backfill/cache/92cd6bdba03415b751077df6b29ba46558d6ad5c9fe698ada8025b5deac2a9b6/response.json` |
| 3 | 200 | `7cc42de32bf8594861940987a0e01a7415abaf98a74ebc1151bbf66e2a22e764` | `data/raw/liquipedia/backfill/cache/7cc42de32bf8594861940987a0e01a7415abaf98a74ebc1151bbf66e2a22e764/response.json` |
| 4 | 300 | `a9f5d205135185d1ab5112dd1f64993475b06f44daba65bc1d131ccf9fb8ae6a` | `data/raw/liquipedia/backfill/cache/a9f5d205135185d1ab5112dd1f64993475b06f44daba65bc1d131ccf9fb8ae6a/response.json` |
| 5 | 400 | `0a98b0a00557983e88451b897540dd519acf33c0e9dec05c52ec88bfdc63bb3d` | `data/raw/liquipedia/backfill/cache/0a98b0a00557983e88451b897540dd519acf33c0e9dec05c52ec88bfdc63bb3d/response.json` |
| 6 | 500 | `fcde7443b0a6611f668c80eba7cd2a85455985b98d026a65e021f89f2a5259c6` | `data/raw/liquipedia/backfill/cache/fcde7443b0a6611f668c80eba7cd2a85455985b98d026a65e021f89f2a5259c6/response.json` |
| 7 | 600 | `bc2e4bd71894d8fa40015393f2c3a61a6f4595309f553e2db61d653e9010acb7` | `data/raw/liquipedia/backfill/cache/bc2e4bd71894d8fa40015393f2c3a61a6f4595309f553e2db61d653e9010acb7/response.json` |
| 8 | 700 | `d3ae754cd59019247712e60e734692eca2e77b16c81a599047bebc44bcc2d9a4` | `data/raw/liquipedia/backfill/cache/d3ae754cd59019247712e60e734692eca2e77b16c81a599047bebc44bcc2d9a4/response.json` |

### 2026-07-pilot

- Configuration hash: `0b40ae8811d6140590657c976ed350d44ab98c9d8289bde8c1d6a57221610258`
- Checkpoint: `data/backfill/runs/m3_20260701_20260727_0b40ae8811d6/checkpoint.json`
- Cache root: `data/raw/liquipedia/backfill/cache`
- Execution policy: `verified_cache_only`

| Sequence | Offset | Request hash | Cache response |
| ---: | ---: | --- | --- |
| 1 | 0 | `9f0b310bee831a6c921fb568cdb5e71a979ebe9832f3e22b29c4e2afa21371c6` | `data/raw/liquipedia/backfill/cache/9f0b310bee831a6c921fb568cdb5e71a979ebe9832f3e22b29c4e2afa21371c6/response.json` |
| 2 | 100 | `0060ee0181d4b51e1c477ee857c41e08b8b9a0b40c8e04f65b924b47b98bfd66` | `data/raw/liquipedia/backfill/cache/0060ee0181d4b51e1c477ee857c41e08b8b9a0b40c8e04f65b924b47b98bfd66/response.json` |
| 3 | 200 | `67826fa9b78af34b32cc8e3b1a00715714e07e90279e652d915f583d7535a8e8` | `data/raw/liquipedia/backfill/cache/67826fa9b78af34b32cc8e3b1a00715714e07e90279e652d915f583d7535a8e8/response.json` |
| 4 | 300 | `d32ee8067e69bdc8925dc0611817bb4874318cda2021eb2c1f8080e23b66cda2` | `data/raw/liquipedia/backfill/cache/d32ee8067e69bdc8925dc0611817bb4874318cda2021eb2c1f8080e23b66cda2/response.json` |

## Resume and Approval Boundary

Campaign status is derived read-only from the existing SQLite
ledger and verified cache. Failed, exhausted, unresolved, or
out-of-order state blocks progress. No live execution is exposed
by the campaign coordinator.

The separately approved Stage B command would be:

```bash
.venv/bin/python scripts/plan_liquipedia_history_campaign.py \
  --check-partition-readiness 2022-Q1 && \
.venv/bin/python scripts/backfill_liquipedia_history.py \
  --start 2022-01-01T00:00:00Z \
  --end 2022-04-01T00:00:00Z \
  --tier 1 \
  --tier 2 \
  --page-size 100 \
  --max-requests 8 \
  --hourly-limit 54 \
  --request-interval-seconds 67 \
  --timeout-seconds 30 \
  --execute \
  --confirm-live-request-budget 8
```

This command is recorded for review and was not executed in Stage A.
