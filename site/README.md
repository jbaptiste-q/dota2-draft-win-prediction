# Draft Lab deployment

This directory packages the frozen Draft Assistant v1 product for deployment.
It is a thin runtime adapter, not a second product implementation.

At build time the Worker imports:

- the canonical HTML, CSS, and JavaScript from
  `src/draft_ai_assistant/web/`;
- the reviewed, SHA-256-pinned JSON inference snapshot from
  `src/draft_ai_assistant/resources/`; and
- the product-specific social preview from `public/og.png`.

It mirrors the five public FastAPI routes used by Draft Lab:

- `GET /api/v1/health`
- `GET /api/v1/heroes`
- `GET /api/v1/model-card`
- `POST /api/v1/analyze`
- `POST /api/v1/replacement-comparisons`

The parity suite generates reference responses from the canonical Python
service and compares them with the deployment Worker. The deployment contains
no Liquipedia credential, authenticated response, training dataset, local
database, checkpoint, or executable model bundle.

## Validate locally

Node.js `>=22.13.0` and the repository's Python dependencies are required.

```bash
npm ci
npm test
npm run typecheck
npm run lint
```

`npm test` creates the deployment build and runs the cross-runtime contract
checks. Generated `dist/`, `.wrangler/`, and dependency directories remain
local-only.
