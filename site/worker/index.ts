/**
 * Cloudflare Worker adapter for the frozen FastAPI Draft Assistant contract.
 *
 * The Python service remains canonical. This module imports the same immutable
 * JSON snapshot and static frontend source files at build time, then mirrors
 * only the five public v1 endpoints required by the product.
 */
import canonicalAppJavaScript from "../../src/draft_ai_assistant/web/app.js?raw";
import canonicalHtml from "../../src/draft_ai_assistant/web/index.html?raw";
import canonicalStyles from "../../src/draft_ai_assistant/web/styles.css?raw";
import snapshotSource from "../../src/draft_ai_assistant/resources/development_candidate_v0.json?raw";

interface Env {
  ASSETS?: {
    fetch(request: Request): Promise<Response>;
  };
}

interface Hero {
  hero_key: string;
  display_name: string;
}

interface Snapshot {
  artifact_fingerprint: string;
  artifact_id: string;
  evidence: {
    candidate_brier_score: number;
    candidate_log_loss: number;
    locked_test_evaluated: false;
    q4_rows: number;
    readiness_gate_passed: false;
    readiness_reference: string;
    reference_brier_score: number;
    reference_log_loss: number;
  };
  heroes: Hero[];
  limitations: string[];
  model: {
    probability_method: "raw_logistic";
    intercept_log_odds: number;
    radiant_hero_log_odds: Record<string, number>;
    dire_hero_log_odds: Record<string, number>;
  };
  schema_version: "draft-ai-inference-snapshot-v1";
  source: {
    candidate_id: string;
    candidate_fingerprint: string;
    source_bundle_fingerprint: string;
    fit_cutoff_utc_exclusive: string;
    fit_rows: number;
  };
  status: "development_candidate";
}

interface AnalyzeRequest {
  radiant_picks: string[];
  dire_picks: string[];
}

interface ReplacementRequest extends AnalyzeRequest {
  side: "radiant" | "dire";
  hero_to_replace: string;
  replacement_hero: string;
}

const SNAPSHOT_SHA256 =
  "bfb7fc8d907e77057cafaef8109a4aec8085915c9215f0dc43cc15ff61dc1a61";
const HERO_PORTRAIT_KEY_PATTERN = /^[a-z0-9-]+\.webp$/;
const BRAND_ASSET_PATTERN = /^dota2-logo-symbol\.png$/;
const SECURITY_HEADERS: Record<string, string> = {
  "content-security-policy":
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; " +
    "img-src 'self' data:; connect-src 'self'; object-src 'none'; " +
    "base-uri 'self'; frame-ancestors 'none'",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
};

let verifiedSnapshot: Promise<Snapshot> | undefined;

function isRecord(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

function compareStrings(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.keys(value)
        .sort(compareStrings)
        .map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}

async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

function validateSnapshot(value: unknown): asserts value is Snapshot {
  if (!isRecord(value)) {
    throw new Error("Snapshot root is not an object.");
  }
  const model = value.model;
  const source = value.source;
  const evidence = value.evidence;
  if (
    value.schema_version !== "draft-ai-inference-snapshot-v1" ||
    value.status !== "development_candidate" ||
    typeof value.artifact_fingerprint !== "string" ||
    !Array.isArray(value.heroes) ||
    !Array.isArray(value.limitations) ||
    !isRecord(model) ||
    !isRecord(source) ||
    !isRecord(evidence)
  ) {
    throw new Error("Snapshot contract is incompatible.");
  }

  const keys = value.heroes.map((hero) => {
    if (
      !isRecord(hero) ||
      typeof hero.hero_key !== "string" ||
      typeof hero.display_name !== "string"
    ) {
      throw new Error("Snapshot hero catalog is incompatible.");
    }
    return hero.hero_key;
  });
  if (
    keys.length === 0 ||
    new Set(keys).size !== keys.length ||
    keys.some((key, index) => index > 0 && key < keys[index - 1])
  ) {
    throw new Error("Snapshot hero catalog is not sorted and unique.");
  }

  const radiant = model.radiant_hero_log_odds;
  const dire = model.dire_hero_log_odds;
  if (
    model.probability_method !== "raw_logistic" ||
    typeof model.intercept_log_odds !== "number" ||
    !Number.isFinite(model.intercept_log_odds) ||
    !isRecord(radiant) ||
    !isRecord(dire) ||
    Object.keys(radiant).length !== keys.length ||
    Object.keys(dire).length !== keys.length ||
    keys.some(
      (key) =>
        typeof radiant[key] !== "number" ||
        !Number.isFinite(radiant[key]) ||
        typeof dire[key] !== "number" ||
        !Number.isFinite(dire[key]),
    )
  ) {
    throw new Error("Snapshot model coefficients are incompatible.");
  }
  if (
    value.limitations.length === 0 ||
    value.limitations.some(
      (limitation) =>
        typeof limitation !== "string" || limitation.length === 0,
    )
  ) {
    throw new Error("Snapshot limitations are incompatible.");
  }
}

async function loadVerifiedSnapshot(): Promise<Snapshot> {
  if (!verifiedSnapshot) {
    verifiedSnapshot = (async () => {
      if ((await sha256(snapshotSource)) !== SNAPSHOT_SHA256) {
        throw new Error("Inference snapshot file hash verification failed.");
      }
      const parsed: unknown = JSON.parse(snapshotSource);
      validateSnapshot(parsed);
      return parsed;
    })();
  }
  return verifiedSnapshot;
}

function responseHeaders(contentType: string): Headers {
  return new Headers({
    ...SECURITY_HEADERS,
    "cache-control": "no-store",
    "content-type": contentType,
  });
}

function staticResponse(body: string, contentType: string): Response {
  return new Response(body, {
    status: 200,
    headers: new Headers({
      ...SECURITY_HEADERS,
      "cache-control": "public, max-age=300",
      "content-type": contentType,
    }),
  });
}

function escapeHtmlAttribute(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function socialMetadata(origin: string): string {
  const home = escapeHtmlAttribute(`${origin}/`);
  const image = escapeHtmlAttribute(`${origin}/og.png`);
  return [
    "    <!-- deployment-social-metadata -->",
    '    <meta property="og:type" content="website">',
    '    <meta property="og:title" content="Dota 2 Draft Lab — Radiant vs Dire">',
    '    <meta property="og:description" content="Build two completed Dota 2 lineups and reveal an explainable battle forecast.">',
    `    <meta property="og:url" content="${home}">`,
    `    <meta property="og:image" content="${image}">`,
    '    <meta name="twitter:card" content="summary_large_image">',
    '    <meta name="twitter:title" content="Dota 2 Draft Lab — Radiant vs Dire">',
    '    <meta name="twitter:description" content="Build two completed Dota 2 lineups and reveal an explainable battle forecast.">',
    `    <meta name="twitter:image" content="${image}">`,
  ].join("\n");
}

function renderHtml(origin: string): string {
  return canonicalHtml.replace(
    "  </head>",
    `${socialMetadata(origin)}\n  </head>`,
  );
}

async function assetResponse(
  request: Request,
  env: Env,
  contentType = "image/png",
): Promise<Response> {
  if (!env.ASSETS) {
    return jsonResponse(
      {
        detail: {
          code: "not_found",
          message: "Route not found.",
        },
      },
      404,
    );
  }
  const asset = await env.ASSETS.fetch(request);
  if (!asset.ok) {
    return asset;
  }
  const headers = new Headers(asset.headers);
  for (const [key, value] of Object.entries(SECURITY_HEADERS)) {
    headers.set(key, value);
  }
  headers.set("cache-control", "public, max-age=86400");
  headers.set("content-type", contentType);
  return new Response(asset.body, {
    status: asset.status,
    statusText: asset.statusText,
    headers,
  });
}

function remapAssetRequest(request: Request, pathname: string): Request {
  const assetUrl = new URL(request.url);
  assetUrl.pathname = pathname;
  return new Request(assetUrl.toString(), request);
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: responseHeaders("application/json; charset=utf-8"),
  });
}

function methodNotAllowed(allowedMethod: "GET" | "POST"): Response {
  const response = jsonResponse({ detail: "Method Not Allowed" }, 405);
  response.headers.set("allow", allowedMethod);
  return response;
}

function invalidRequest(message: string): Response {
  return jsonResponse(
    {
      detail: {
        code: "invalid_request",
        message,
      },
    },
    422,
  );
}

function validateExactKeys(
  value: Record<string, unknown>,
  expected: string[],
): string | null {
  const actual = Object.keys(value).sort(compareStrings);
  const wanted = [...expected].sort(compareStrings);
  if (
    actual.length !== wanted.length ||
    actual.some((key, index) => key !== wanted[index])
  ) {
    return "Request fields do not match the published contract.";
  }
  return null;
}

function validatePicks(
  value: unknown,
  label: "Radiant" | "Dire",
): string | null {
  if (!Array.isArray(value) || value.length !== 5) {
    return `${label} must contain exactly five heroes.`;
  }
  if (
    value.some(
      (hero) =>
        typeof hero !== "string" ||
        hero.length === 0 ||
        hero !== hero.trim(),
    )
  ) {
    return "Hero keys must be non-empty exact catalog identifiers.";
  }
  if (new Set(value).size !== 5) {
    return `${label} must contain five unique heroes.`;
  }
  return null;
}

function parseAnalyzeRequest(value: unknown): AnalyzeRequest | string {
  if (!isRecord(value)) {
    return "Request body must be a JSON object.";
  }
  const keyError = validateExactKeys(value, [
    "radiant_picks",
    "dire_picks",
  ]);
  if (keyError) {
    return keyError;
  }
  const radiantError = validatePicks(value.radiant_picks, "Radiant");
  if (radiantError) {
    return radiantError;
  }
  const direError = validatePicks(value.dire_picks, "Dire");
  if (direError) {
    return direError;
  }
  const radiant = value.radiant_picks as string[];
  const dire = value.dire_picks as string[];
  if (new Set([...radiant, ...dire]).size !== 10) {
    return "A hero cannot appear on both sides of the same draft.";
  }
  return {
    radiant_picks: [...radiant],
    dire_picks: [...dire],
  };
}

function parseReplacementRequest(
  value: unknown,
): ReplacementRequest | string {
  if (!isRecord(value)) {
    return "Request body must be a JSON object.";
  }
  const keyError = validateExactKeys(value, [
    "radiant_picks",
    "dire_picks",
    "side",
    "hero_to_replace",
    "replacement_hero",
  ]);
  if (keyError) {
    return keyError;
  }
  const base = parseAnalyzeRequest({
    radiant_picks: value.radiant_picks,
    dire_picks: value.dire_picks,
  });
  if (typeof base === "string") {
    return base;
  }
  if (value.side !== "radiant" && value.side !== "dire") {
    return "Side must be either radiant or dire.";
  }
  for (const key of ["hero_to_replace", "replacement_hero"] as const) {
    const hero = value[key];
    if (
      typeof hero !== "string" ||
      hero.length === 0 ||
      hero !== hero.trim()
    ) {
      return (
        "Replacement hero keys must be non-empty exact catalog " +
        "identifiers."
      );
    }
  }
  const side = value.side;
  const outgoing = value.hero_to_replace as string;
  const incoming = value.replacement_hero as string;
  const selected =
    side === "radiant" ? base.radiant_picks : base.dire_picks;
  if (!selected.includes(outgoing)) {
    return "The outgoing hero must belong to the selected side.";
  }
  if (incoming === outgoing) {
    return "The incoming hero must differ from the outgoing hero.";
  }
  if ([...base.radiant_picks, ...base.dire_picks].includes(incoming)) {
    return "The incoming hero must be absent from the completed draft.";
  }
  return {
    ...base,
    side,
    hero_to_replace: outgoing,
    replacement_hero: incoming,
  };
}

function unsupportedResponse(heroKeys: string[]): Response {
  const sorted = [...new Set(heroKeys)].sort(compareStrings);
  return jsonResponse(
    {
      detail: {
        code: "unsupported_hero",
        message: `Unsupported hero keys: ${sorted.join(", ")}.`,
        hero_keys: sorted,
      },
    },
    422,
  );
}

function unsupportedHeroes(
  snapshot: Snapshot,
  ...groups: string[][]
): string[] {
  const catalog = new Set(snapshot.heroes.map((hero) => hero.hero_key));
  return [...new Set(groups.flat().filter((hero) => !catalog.has(hero)))].sort(
    compareStrings,
  );
}

/**
 * Error-free summation equivalent to Python's math.fsum for this finite,
 * bounded coefficient vector.
 */
function fsum(values: number[]): number {
  const partials: number[] = [];
  for (let value of values) {
    let index = 0;
    for (const partial of partials) {
      let highValue = value;
      let lowValue = partial;
      if (Math.abs(highValue) < Math.abs(lowValue)) {
        [highValue, lowValue] = [lowValue, highValue];
      }
      const high = highValue + lowValue;
      const low = lowValue - (high - highValue);
      if (low !== 0) {
        partials[index] = low;
        index += 1;
      }
      value = high;
    }
    partials.length = index;
    partials.push(value);
  }
  return partials.reduceRight((total, partial) => total + partial, 0);
}

function sigmoid(logOdds: number): number {
  if (logOdds >= 0) {
    const inverse = Math.exp(-logOdds);
    return 1 / (1 + inverse);
  }
  const exponential = Math.exp(logOdds);
  return exponential / (1 + exponential);
}

function modelDisclosure(snapshot: Snapshot): Record<string, unknown> {
  return {
    status: snapshot.status,
    readiness_gate_passed: snapshot.evidence.readiness_gate_passed,
    locked_test_evaluated: snapshot.evidence.locked_test_evaluated,
    candidate_id: snapshot.source.candidate_id,
    candidate_fingerprint: snapshot.source.candidate_fingerprint,
    artifact_fingerprint: snapshot.artifact_fingerprint,
    source_bundle_fingerprint: snapshot.source.source_bundle_fingerprint,
    fit_cutoff_utc_exclusive: snapshot.source.fit_cutoff_utc_exclusive,
    fit_rows: snapshot.source.fit_rows,
    probability_method: snapshot.model.probability_method,
  };
}

async function analyze(
  snapshot: Snapshot,
  request: AnalyzeRequest,
): Promise<Record<string, unknown>> {
  const radiant = [...request.radiant_picks].sort(compareStrings);
  const dire = [...request.dire_picks].sort(compareStrings);
  const heroNames = new Map(
    snapshot.heroes.map((hero) => [hero.hero_key, hero.display_name]),
  );
  const contributions = [
    ...radiant.map((heroKey) => ({
      hero_key: heroKey,
      display_name: heroNames.get(heroKey)!,
      side: "radiant",
      coefficient_log_odds:
        snapshot.model.radiant_hero_log_odds[heroKey],
    })),
    ...dire.map((heroKey) => ({
      hero_key: heroKey,
      display_name: heroNames.get(heroKey)!,
      side: "dire",
      coefficient_log_odds: snapshot.model.dire_hero_log_odds[heroKey],
    })),
  ]
    .map((contribution) => ({
      ...contribution,
      odds_multiplier: Math.exp(contribution.coefficient_log_odds),
      supports:
        contribution.coefficient_log_odds > 0
          ? "radiant"
          : contribution.coefficient_log_odds < 0
            ? "dire"
            : "neutral",
    }))
    .sort((left, right) => {
      const magnitude =
        Math.abs(right.coefficient_log_odds) -
        Math.abs(left.coefficient_log_odds);
      if (magnitude !== 0) {
        return magnitude;
      }
      const side = compareStrings(left.side, right.side);
      return side !== 0
        ? side
        : compareStrings(left.hero_key, right.hero_key);
    });

  const coefficients = contributions.map(
    (item) => item.coefficient_log_odds,
  );
  const draftLogOdds = fsum([
    snapshot.model.intercept_log_odds,
    ...coefficients,
  ]);
  const radiantProbability = sigmoid(draftLogOdds);
  const direProbability = 1 - radiantProbability;
  const reconstruction =
    snapshot.model.intercept_log_odds +
    coefficients.reduce(
      (total, coefficient) => total + coefficient,
      0,
    );
  const predictionId = await sha256(
    canonicalJson({
      radiant_picks: radiant,
      dire_picks: dire,
      artifact_fingerprint: snapshot.artifact_fingerprint,
    }),
  );

  return {
    schema_version: "draft-assistant-analysis-v1",
    prediction_id: predictionId,
    draft: {
      representation: "unordered_side_relative_completed_picks",
      radiant_picks: radiant,
      dire_picks: dire,
    },
    probability: {
      radiant_win: radiantProbability,
      dire_win: direProbability,
      favored_side:
        radiantProbability > 0.5
          ? "radiant"
          : radiantProbability < 0.5
            ? "dire"
            : "even",
      method: snapshot.model.probability_method,
    },
    explanation: {
      surface: "base_estimator_log_odds",
      interpretation: "associative_not_causal",
      baseline_log_odds: snapshot.model.intercept_log_odds,
      baseline_radiant_win_probability: sigmoid(
        snapshot.model.intercept_log_odds,
      ),
      draft_log_odds: draftLogOdds,
      reconstruction_error: Math.abs(draftLogOdds - reconstruction),
      contributions,
    },
    model: modelDisclosure(snapshot),
    limitations: snapshot.limitations,
  };
}

async function replacementComparison(
  snapshot: Snapshot,
  request: ReplacementRequest,
): Promise<Record<string, unknown>> {
  const baseline = await analyze(snapshot, request);
  const radiant = [...request.radiant_picks];
  const dire = [...request.dire_picks];
  const selected = request.side === "radiant" ? radiant : dire;
  selected[selected.indexOf(request.hero_to_replace)] =
    request.replacement_hero;
  const replacement = await analyze(snapshot, {
    radiant_picks: radiant,
    dire_picks: dire,
  });
  const baselineProbability = baseline.probability as Record<string, number>;
  const replacementProbability =
    replacement.probability as Record<string, number>;
  const radiantDelta =
    replacementProbability.radiant_win - baselineProbability.radiant_win;
  const direDelta =
    replacementProbability.dire_win - baselineProbability.dire_win;
  const comparisonId = await sha256(
    canonicalJson({
      schema_version: "draft-assistant-replacement-comparison-v1",
      side: request.side,
      hero_to_replace: request.hero_to_replace,
      replacement_hero: request.replacement_hero,
      baseline_prediction_id: baseline.prediction_id,
      replacement_prediction_id: replacement.prediction_id,
      artifact_fingerprint: snapshot.artifact_fingerprint,
    }),
  );
  const heroNames = new Map(
    snapshot.heroes.map((hero) => [hero.hero_key, hero.display_name]),
  );
  const scenario = (result: Record<string, unknown>) => ({
    prediction_id: result.prediction_id,
    draft: result.draft,
    probability: result.probability,
  });

  return {
    schema_version: "draft-assistant-replacement-comparison-v1",
    comparison_id: comparisonId,
    interpretation: "associative_model_comparison_not_causal",
    recommendation: false,
    side: request.side,
    outgoing: {
      hero_key: request.hero_to_replace,
      display_name: heroNames.get(request.hero_to_replace)!,
    },
    incoming: {
      hero_key: request.replacement_hero,
      display_name: heroNames.get(request.replacement_hero)!,
    },
    baseline: scenario(baseline),
    replacement: scenario(replacement),
    delta: {
      radiant_win: radiantDelta,
      dire_win: direDelta,
      selected_side_win:
        request.side === "radiant" ? radiantDelta : direDelta,
    },
    model: baseline.model,
    limitations: [
      "This is a user-directed one-for-one comparison of two completed " +
        "drafts, not a recommendation.",
      "The change is an associative model comparison, not a causal estimate.",
      "The additive model does not evaluate hero synergy, counters, roles, " +
        "lanes, bans, pick order, patch, teams, or players.",
      ...snapshot.limitations,
    ],
  };
}

async function requestJson(request: Request): Promise<unknown | Response> {
  try {
    return await request.json();
  } catch {
    return jsonResponse(
      {
        detail: {
          code: "invalid_json",
          message: "Request body must be valid JSON.",
        },
      },
      422,
    );
  }
}

const worker = {
  async fetch(
    request: Request,
    env: Env = {},
  ): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/") {
      return staticResponse(
        renderHtml(url.origin),
        "text/html; charset=utf-8",
      );
    }
    if (
      request.method === "GET" &&
      url.pathname === "/static/styles.css"
    ) {
      return staticResponse(canonicalStyles, "text/css; charset=utf-8");
    }
    if (request.method === "GET" && url.pathname === "/static/app.js") {
      return staticResponse(
        canonicalAppJavaScript,
        "text/javascript; charset=utf-8",
      );
    }
    if (request.method === "GET" && url.pathname === "/og.png") {
      return assetResponse(request, env);
    }
    if (
      request.method === "GET" &&
      url.pathname.startsWith("/static/heroes/")
    ) {
      const file = url.pathname.slice("/static/heroes/".length);
      if (!HERO_PORTRAIT_KEY_PATTERN.test(file)) {
        return jsonResponse(
          { detail: { code: "not_found", message: "Route not found." } },
          404,
        );
      }
      return assetResponse(
        remapAssetRequest(request, `/heroes/${file}`),
        env,
        "image/webp",
      );
    }
    if (
      request.method === "GET" &&
      url.pathname.startsWith("/static/brand/")
    ) {
      const file = url.pathname.slice("/static/brand/".length);
      if (!BRAND_ASSET_PATTERN.test(file)) {
        return jsonResponse(
          { detail: { code: "not_found", message: "Route not found." } },
          404,
        );
      }
      return assetResponse(
        remapAssetRequest(request, `/brand/${file}`),
        env,
        "image/png",
      );
    }
    let snapshot: Snapshot;
    try {
      snapshot = await loadVerifiedSnapshot();
    } catch {
      return jsonResponse(
        {
          detail: {
            code: "snapshot_unavailable",
            message: "The verified inference snapshot is unavailable.",
          },
        },
        503,
      );
    }

    if (request.method === "GET" && url.pathname === "/api/v1/health") {
      return jsonResponse({
        schema_version: "draft-assistant-health-v1",
        status: "ok",
        model_loaded: true,
        model_status: snapshot.status,
        candidate_id: snapshot.source.candidate_id,
        artifact_fingerprint: snapshot.artifact_fingerprint,
      });
    }
    if (request.method === "GET" && url.pathname === "/api/v1/heroes") {
      return jsonResponse({
        schema_version: "draft-assistant-heroes-v1",
        heroes: snapshot.heroes,
        count: snapshot.heroes.length,
      });
    }
    if (
      request.method === "GET" &&
      url.pathname === "/api/v1/model-card"
    ) {
      return jsonResponse({
        schema_version: "draft-assistant-model-card-v1",
        status: snapshot.status,
        candidate_id: snapshot.source.candidate_id,
        artifact_fingerprint: snapshot.artifact_fingerprint,
        fit: {
          rows: snapshot.source.fit_rows,
          cutoff_utc_exclusive:
            snapshot.source.fit_cutoff_utc_exclusive,
          hero_count: snapshot.heroes.length,
          representation: "unordered_side_relative_completed_picks",
        },
        evaluation: {
          period: "2025-Q4",
          rows: snapshot.evidence.q4_rows,
          reference: snapshot.evidence.readiness_reference,
          candidate: {
            log_loss: snapshot.evidence.candidate_log_loss,
            brier_score: snapshot.evidence.candidate_brier_score,
          },
          reference_metrics: {
            log_loss: snapshot.evidence.reference_log_loss,
            brier_score: snapshot.evidence.reference_brier_score,
          },
          readiness_gate_passed:
            snapshot.evidence.readiness_gate_passed,
          locked_test_evaluated:
            snapshot.evidence.locked_test_evaluated,
          conclusion: "candidate_did_not_beat_reference",
        },
        capabilities: {
          completed_draft_probability: true,
          local_hero_contributions: true,
          bans: false,
          partial_drafts: false,
          recommendations: false,
          first_pick: false,
          global_draft_order: false,
        },
        limitations: snapshot.limitations,
      });
    }
    if (
      request.method === "POST" &&
      url.pathname === "/api/v1/analyze"
    ) {
      const body = await requestJson(request);
      if (body instanceof Response) {
        return body;
      }
      const parsed = parseAnalyzeRequest(body);
      if (typeof parsed === "string") {
        return invalidRequest(parsed);
      }
      const unsupported = unsupportedHeroes(
        snapshot,
        parsed.radiant_picks,
        parsed.dire_picks,
      );
      if (unsupported.length > 0) {
        return unsupportedResponse(unsupported);
      }
      return jsonResponse(await analyze(snapshot, parsed));
    }
    if (
      request.method === "POST" &&
      url.pathname === "/api/v1/replacement-comparisons"
    ) {
      const body = await requestJson(request);
      if (body instanceof Response) {
        return body;
      }
      const parsed = parseReplacementRequest(body);
      if (typeof parsed === "string") {
        return invalidRequest(parsed);
      }
      const unsupported = unsupportedHeroes(
        snapshot,
        parsed.radiant_picks,
        parsed.dire_picks,
        [parsed.replacement_hero],
      );
      if (unsupported.length > 0) {
        return unsupportedResponse(unsupported);
      }
      return jsonResponse(await replacementComparison(snapshot, parsed));
    }

    const allowedMethods: Record<string, "GET" | "POST"> = {
      "/api/v1/health": "GET",
      "/api/v1/heroes": "GET",
      "/api/v1/model-card": "GET",
      "/api/v1/analyze": "POST",
      "/api/v1/replacement-comparisons": "POST",
    };
    const allowed = allowedMethods[url.pathname];
    if (allowed) {
      return methodNotAllowed(allowed);
    }

    return jsonResponse(
      {
        detail: {
          code: "not_found",
          message: "Route not found.",
        },
      },
      404,
    );
  },
};

export default worker;
