"""Static, no-browser checks for the local Draft Lab product surface.

These assertions target the *invariants* the product has committed to — frozen
API contracts, no external runtime dependencies, accessibility affordances,
and the mandatory safety disclosures — rather than pinning the exact literal
markup of any single visual design pass.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


WEB_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "draft_ai_assistant"
    / "web"
)

SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "draft_ai_assistant"
    / "resources"
    / "development_candidate_v0.json"
)

ATTRIBUTE_TOKENS = ("str", "agi", "int", "universal")


def _read(name: str) -> str:
    return (WEB_ROOT / name).read_text(encoding="utf-8")


def _catalog_hero_keys() -> set[str]:
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return {hero["hero_key"] for hero in snapshot["heroes"]}


def _css_hex_variable(styles: str, variable: str) -> str:
    match = re.search(
        rf"{re.escape(variable)}:\s*(#[0-9a-fA-F]{{6}})\s*;",
        styles,
    )
    assert match, f"{variable} must be a six-digit hex color"
    return match.group(1)


def _relative_luminance(hex_color: str) -> float:
    channels = [
        int(hex_color[index : index + 2], 16) / 255
        for index in (1, 3, 5)
    ]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return (
        0.2126 * linear[0]
        + 0.7152 * linear[1]
        + 0.0722 * linear[2]
    )


def _contrast_ratio(left: str, right: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(left), _relative_luminance(right)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def test_frontend_uses_only_same_origin_local_assets() -> None:
    combined = "\n".join(
        _read(name)
        for name in ("index.html", "styles.css", "app.js")
    )

    assert "http://" not in combined
    assert "https://" not in combined
    assert 'href="/static/styles.css?v=20260802-dota-stage-4"' in combined
    assert 'src="/static/app.js?v=20260802-dota-stage-4"' in combined
    # Portraits remain a same-origin, replaceable presentation layer with no
    # remote runtime dependency.
    assert 'HERO_PORTRAIT_BASE_PATH = "/static/heroes"' in combined
    assert "encodeURIComponent(heroKey)" in combined
    assert "/static/fonts/" not in combined


def test_javascript_dom_id_references_exist_in_html() -> None:
    html = _read("index.html")
    script = _read("app.js")
    html_ids = set(re.findall(r'\bid="([^"]+)"', html))
    javascript_ids = set(
        re.findall(r'document\.querySelector\("#([^"]+)"\)', script)
    )

    assert len(html_ids) == len(re.findall(r'\bid="([^"]+)"', html))
    assert javascript_ids
    assert javascript_ids <= html_ids


def test_frontend_pins_the_public_api_contracts() -> None:
    script = _read("app.js")

    assert '"/api/v1/heroes"' in script
    assert '"/api/v1/analyze"' in script
    assert '"/api/v1/replacement-comparisons"' in script
    assert '"/api/v1/model-card"' in script
    assert '"draft-assistant-heroes-v1"' in script
    assert '"draft-assistant-analysis-v1"' in script
    assert '"draft-assistant-replacement-comparison-v1"' in script
    assert '"draft-assistant-model-card-v1"' in script
    assert "radiant_picks" in script
    assert "dire_picks" in script


def test_frontend_example_is_fixed_one_click_workflow_not_recommendation() -> None:
    html = _read("index.html")
    script = _read("app.js")

    assert 'id="try-example"' in html
    assert "Enter example battle" in html
    assert "Fixed workflow example for demonstrating the interface." in html
    assert "It is not a hero recommendation." in html
    assert (
        'radiant: Object.freeze(["axe", "puck", "lina", "tusk", "luna"])'
        in script
    )
    assert (
        'dire: Object.freeze(["doom", "invoker", "tiny", "phoenix", '
        '"slark"])' in script
    )
    assert (
        'elements.tryExample.addEventListener("click", tryExampleDraft)'
        in script
    )
    assert "state.picks.radiant = EXAMPLE_DRAFT.radiant.map(" in script
    assert "state.picks.dire = EXAMPLE_DRAFT.dire.map(" in script
    assert "await analyzeDraft();" in script


def test_frontend_publishes_q4_evidence_and_locked_test_disclosure() -> None:
    html = _read("index.html")
    script = _read("app.js")

    for label in (
        "Published model evidence",
        "Why this result stays experimental",
        "2025-Q4 calibration period",
        "Log loss",
        "Brier score",
        "Candidate",
        "Empirical prior",
        "Readiness gate",
        "Locked 2026-Q1",
        "Fit cutoff",
    ):
        assert label in html

    for evidence_id in (
        "model-card-status",
        "evidence-candidate-log-loss",
        "evidence-reference-log-loss",
        "evidence-candidate-brier",
        "evidence-reference-brier",
        "evidence-gate",
        "evidence-locked",
        "evidence-cutoff",
    ):
        assert f'id="{evidence_id}"' in html
        assert f'"#{evidence_id}"' in script

    assert "evaluation.readiness_gate_passed === true" in script
    assert "evaluation.locked_test_evaluated === true" in script
    assert "Evidence unavailable; draft analysis remains available." in script

    # The evidence panel is a native <details> collapsed by default so it no
    # longer front-loads statistical caveats ahead of the interactive tool.
    assert '<details class="model-evidence-panel" id="evidence-details">' in html


def test_frontend_makes_the_product_boundary_visible() -> None:
    html = _read("index.html")
    normalized_html = " ".join(html.split())

    for disclosure in (
        "Experimental model",
        "Completed drafts only · 5v5",
        "Completed drafts only",
        "No hero recommendations",
        "not readiness-approved",
        "Association is not causation",
        "no authenticated or live data requests",
    ):
        assert disclosure in normalized_html


def test_frontend_uses_dota_faction_vocabulary_without_new_product_scope() -> None:
    html = _read("index.html")
    styles = _read("styles.css")

    assert '<span class="title-radiant">Radiant</span>' in html
    assert '<span class="title-dire">Dire</span>' in html
    assert "The draft battlefield" in html
    assert "Two lineups. One forecast." in html
    assert ".draft-workspace::before" in styles
    assert ".faction-showcase" in styles
    assert ".outcome-clash" in styles
    assert "var(--radiant)" in styles
    assert "var(--dire)" in styles

    for unsupported_scope in (
        "lane assignment",
        "role prediction",
        "ban recommendation",
        "counter recommendation",
    ):
        assert unsupported_scope not in html.casefold()

    assert "Largest absolute contribution first" in html


def test_frontend_has_user_directed_replacement_comparison_not_ranking() -> None:
    html = _read("index.html")
    script = _read("app.js")

    result_grid = html.index('<div class="result-grid">')
    replacement_panel = html.index('id="replacement-explorer"')
    evidence_grid = html.index('<div class="evidence-grid">')
    assert result_grid < replacement_panel < evidence_grid

    for element_id in (
        "replacement-side",
        "replacement-outgoing",
        "replacement-incoming",
        "compare-replacement",
        "replacement-status",
        "replacement-output",
        "replacement-baseline-probability",
        "replacement-scenario-probability",
        "replacement-probability-delta",
    ):
        assert f'id="{element_id}"' in html
        assert f'"#{element_id}"' in script

    for disclosure in (
        "What-if replacement",
        "Not a recommendation",
        "user-directed completed-draft comparison",
        "does not rank heroes",
        "associative model comparison, not a causal claim",
        "ignores synergy, counters, roles, lanes",
        "bans, order, patch, teams, and players",
        "Q4 readiness failed",
        "locked Q1 test remains sealed and unevaluated",
    ):
        assert disclosure.casefold() in html.casefold()

    assert "hero_to_replace" in script
    assert "replacement_hero" in script
    assert "associative_model_comparison_not_causal" in script
    assert "payload?.recommendation !== false" in script


def test_frontend_replacement_comparison_validates_echo_and_deltas() -> None:
    script = _read("app.js")

    assert "baseline.prediction_id !== analysis.predictionId" in script
    assert "!draftMatches(baseline.draft, analysis.draft)" in script
    assert "!draftMatches(replacement.draft, expectedReplacement)" in script
    assert "delta.radiant_win - expectedRadiant" in script
    assert "delta.dire_win - expectedDire" in script
    assert "delta.selected_side_win - expectedSelected" in script
    assert 'payload?.model?.status !== "development_candidate"' in script
    assert "payload?.model?.readiness_gate_passed !== false" in script
    assert "payload?.model?.locked_test_evaluated !== false" in script


def test_frontend_invalidates_stale_analysis_and_replacement_responses() -> None:
    script = _read("app.js")

    assert "draftRevision: 0" in script
    assert "comparisonRevision: 0" in script
    assert "lastAnalysis: null" in script
    assert "state.draftRevision += 1" in script
    assert "state.comparisonRevision += 1" in script
    assert "invalidateReplacementExplorer();" in script
    assert "analysis !== state.lastAnalysis" in script
    assert "analysis.draftRevision !== state.draftRevision" in script
    assert "state.analyzing || state.comparing ? \"disabled\" : \"\"" in script
    assert (
        "elements.resetDraft.disabled = state.analyzing || state.comparing"
        in script
    )
    assert "state.comparing || state.heroes.length === 0" in script
    assert "renderDraft();" in script
    assert (
        'elements.compareReplacement.addEventListener(\n'
        '      "click",\n'
        "      compareReplacement,"
    ) in script


def test_frontend_includes_keyboard_and_reduced_motion_support() -> None:
    html = _read("index.html")
    styles = _read("styles.css")
    script = _read("app.js")

    assert 'class="skip-link"' in html
    assert 'aria-live="polite"' in html
    assert "<dialog " in html
    assert "prefers-reduced-motion: reduce" in styles

    # Hero search still jumps into the grid...
    assert 'event.key === "ArrowDown"' in script
    # ...and the grid itself supports full roving keyboard navigation, not
    # just a single first-option jump.
    assert "function navigateHeroOptions(event)" in script
    for key in ('"ArrowRight"', '"ArrowLeft"', '"ArrowDown"', '"ArrowUp"', '"Home"', '"End"'):
        assert key in script
    assert (
        'elements.heroOptions.addEventListener("keydown", navigateHeroOptions);'
        in script
    )
    assert 'button.hero-option:not(:disabled)' in script


def test_frontend_hero_portraits_are_local_with_accessible_fallback() -> None:
    styles = _read("styles.css")
    script = _read("app.js")

    # One shared helper renders every portrait; verify it, and only it, is
    # used across the three surfaces that display a hero.
    assert "function heroPortraitMarkup(hero)" in script
    assert script.count("heroPortraitMarkup(") >= 4  # definition + 3 call sites

    # Decorative image: the enclosing control already carries the full
    # accessible name, so the <img> itself must not double-announce it.
    assert 'alt=""' in script
    assert 'class="hero-portrait-fallback"' in script

    # A failed portrait load degrades to the text fallback instead of a
    # broken-image icon. `error` events don't bubble, so this must be a
    # capturing listener rather than a normal delegated one.
    assert "function handlePortraitLoadError(event)" in script
    assert "target.hidden = true" in script
    assert (
        'document.addEventListener("error", handlePortraitLoadError, true);'
        in script
    )

    assert ".hero-portrait" in styles
    assert ".hero-portrait-fallback" in styles


def test_frontend_uses_the_official_dota_mark_inside_a_separate_relic_frame() -> None:
    html = _read("index.html")
    styles = _read("styles.css")
    logo = WEB_ROOT / "brand" / "dota2-logo-symbol.png"
    provenance = WEB_ROOT / "brand" / "README.md"

    assert logo.is_file()
    assert logo.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert hashlib.sha256(logo.read_bytes()).hexdigest() == (
        "249201f03e6045e5959996a2a76e9f07b040d5e3ccf24c6ebe726e86754636ad"
    )
    assert 'src="/static/brand/dota2-logo-symbol.png"' in html
    assert 'class="brand-relic"' in html
    assert ".brand-relic-stone" in styles
    assert ".brand-relic-corners" in styles
    assert "cdn.cloudflare.steamstatic.com" in provenance.read_text(
        encoding="utf-8",
    )


def test_frontend_art_layer_is_large_dynamic_and_replaceable_by_hero_key() -> None:
    html = _read("index.html")
    styles = _read("styles.css")
    script = _read("app.js")

    for element_id in (
        "radiant-showcase",
        "radiant-featured-art",
        "radiant-featured-name",
        "dire-showcase",
        "dire-featured-art",
        "dire-featured-name",
        "outcome-radiant-art",
        "outcome-dire-art",
    ):
        assert f'id="{element_id}"' in html

    assert "function heroPortraitSource(heroKey)" in script
    assert "function renderFactionShowcase(side)" in script
    assert "function renderOutcomeBattle(" in script
    assert "showcase.art.src = heroPortraitSource(hero.hero_key)" in script
    assert "outcomeHero.art.src = heroPortraitSource(heroKey)" in script
    assert ".opening-hero" in styles
    assert ".faction-showcase" in styles
    assert ".outcome-hero" in styles


def test_frontend_portrait_art_is_replaceable_and_not_a_data_contract() -> None:
    script = _read("app.js")

    assert "replaceable presentation-only artwork path" in script.casefold()
    assert "artwork can change without touching product or inference" in script
    assert 'HERO_PORTRAIT_BASE_PATH = "/static/heroes"' in script
    assert "encodeURIComponent(heroKey)" in script
    assert "`${encodeURIComponent(heroKey)}.webp`" in script
    assert _catalog_hero_keys()


def test_frontend_uses_system_ui_type_without_external_font_assets() -> None:
    html = _read("index.html")
    styles = _read("styles.css")

    assert "@font-face" not in styles
    assert "/static/fonts/" not in styles
    assert "/static/fonts/" not in html
    assert "--font-display:" in styles
    assert "ui-serif" in styles
    assert "Georgia" in styles
    assert "-apple-system" in styles
    assert "font-family: var(--font-display);" in styles


def test_frontend_attribute_filters_cover_every_catalog_hero() -> None:
    html = _read("index.html")
    script = _read("app.js")

    assert 'id="attribute-filters"' in html
    for attribute in ("all", "str", "agi", "int", "universal"):
        assert f'data-attr="{attribute}"' in html

    assert "const HERO_ATTRIBUTES = Object.freeze({" in script
    assert "function heroAttribute(heroKey)" in script
    assert "function setAttributeFilter(attribute)" in script
    assert html.count('aria-pressed="true"') == 1
    assert html.count('aria-pressed="false"') == 4
    assert 'button.setAttribute("aria-pressed", String(isActive));' in script

    mapped_keys = set(
        re.findall(r'"([a-z0-9-]+)":"(?:str|agi|int|universal)"', script)
    )
    catalog_keys = _catalog_hero_keys()
    assert mapped_keys == catalog_keys, (
        "the local attribute lookup must cover exactly the heroes in the "
        "frozen catalog — no missing heroes, no stale leftovers"
    )


def test_frontend_core_text_colors_meet_wcag_aa_contrast() -> None:
    styles = _read("styles.css")
    colors = {
        name: _css_hex_variable(styles, name)
        for name in (
            "--bg",
            "--surface",
            "--muted",
            "--radiant",
            "--dire",
            "--accent",
            "--accent-strong",
            "--accent-ink",
            "--amber",
            "--advisory-ink",
        )
    }

    for foreground, background in (
        ("--muted", "--bg"),
        ("--muted", "--surface"),
        ("--radiant", "--bg"),
        ("--radiant", "--surface"),
        ("--dire", "--bg"),
        ("--dire", "--surface"),
        ("--accent-ink", "--accent"),
        ("--accent-ink", "--accent-strong"),
        ("--advisory-ink", "--amber"),
    ):
        assert _contrast_ratio(colors[foreground], colors[background]) >= 4.5


def test_frontend_keeps_art_direction_out_of_the_product_ui() -> None:
    html = _read("index.html")
    styles = _read("styles.css")
    script = _read("app.js")
    combined = "\n".join((html, styles, script)).casefold()

    assert "Hero artwork may evolve" in html
    for rejected_direction in (
        "burn the witch",
        "manga",
        "editorial",
        "licensing review",
        "publication rights",
    ):
        assert rejected_direction not in combined


def test_frontend_prioritizes_product_before_model_evidence() -> None:
    html = _read("index.html")

    assert html.index('id="draft-workspace"') < html.index(
        'id="result-section"'
    )
    assert html.index('id="result-section"') < html.index(
        'id="evidence-details"'
    )


def test_frontend_makes_the_battle_outcome_primary_and_accessible() -> None:
    html = _read("index.html")
    script = _read("app.js")

    probability = html.index('class="probability-card"')
    model = html.index('class="model-card"')
    replacement = html.index('id="replacement-explorer"')
    assert probability < model < replacement

    assert 'id="outcome-verdict"' in html
    assert 'id="radiant-probability"' in html
    assert 'id="dire-probability"' in html
    assert 'id="probability-bar"' in html
    assert 'role="img"' in html
    assert "Radiant advantage" not in html
    assert "`${titleCase(leadingSide)} advantage`" in script
    assert 'elements.probabilityBar.setAttribute(\n      "aria-label"' in script


def test_frontend_uses_portrait_first_five_hero_formations() -> None:
    styles = _read("styles.css")
    script = _read("app.js")

    assert "grid-template-columns: repeat(5, minmax(0, 1fr));" in styles
    assert '<span class="slot-copy">' in script
    assert "${heroPortraitMarkup(hero)}" in script
    assert 'class="slot-select"' in script


def test_frontend_uses_product_aligned_action_hierarchy() -> None:
    html = _read("index.html")

    # Resolving the draft is the dominant battle action. The example and
    # user-directed what-if remain visually subordinate.
    assert 'id="analyze-draft"\n                class="btn btn--battle' in html
    assert 'id="try-example"\n                class="btn btn--secondary' in html
    assert 'id="compare-replacement"\n                  class="btn btn--quiet' in html
    assert 'id="reset-draft" class="btn btn--text"' in html
    assert 'id="close-picker"\n            class="icon-button"' in html


def test_frontend_pick_tally_reflects_all_ten_slots() -> None:
    html = _read("index.html")
    script = _read("app.js")

    radiant_dots = html.count('<span class="tally-dot" data-side="radiant">')
    dire_dots = html.count('<span class="tally-dot" data-side="dire">')
    assert radiant_dots == 5
    assert dire_dots == 5

    assert "function renderPickTally()" in script
    assert "renderPickTally();" in script
