# Liquipedia API Validation Data

The `runs/` directory contains local, authenticated LiquipediaDB API validation
artifacts. It is intentionally excluded from Git.

Each timestamped run contains:

- `response.json`: the decompressed response body returned by the official API.
- `manifest.json`: non-secret request metadata and a response checksum.
- `field_report.json`: machine-readable nested-field inventory and capability verdict.
- `field_report.md`: human-readable validation summary.

Show the zero-request discovery plan:

```bash
python scripts/discover_liquipedia_samples.py \
  --show-plan \
  --as-of-date 2026-07-27
```

After the plan is approved, keep the key as the only line in an ignored local
file and execute the four-request discovery phase:

```bash
mkdir -p .secrets
chmod 700 .secrets
# Create .secrets/liquipedia_api_key using your preferred local editor.
chmod 600 .secrets/liquipedia_api_key
python scripts/discover_liquipedia_samples.py \
  --execute-discovery \
  --as-of-date 2026-07-27 \
  --api-key-file .secrets/liquipedia_api_key
```

Discovery stops after writing `discovery/<timestamp>/selection.json`. Review
the selected IDs before the separately approved, one-request validation:

```bash
python scripts/validate_liquipedia_api.py \
  --selection-file data/validation/liquipedia/discovery/<timestamp>/selection.json \
  --api-key-file .secrets/liquipedia_api_key
```

The validator has no hard-coded default IDs. Discovery makes four requests,
with no pagination or retries and a 61-second interval. Exact-ID validation
makes one additional request.

Never commit the API key or generated response files.
