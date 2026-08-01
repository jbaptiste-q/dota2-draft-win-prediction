"""Static, no-browser checks for the local Draft Lab product surface."""

from __future__ import annotations

import re
from pathlib import Path


WEB_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "draft_ai_assistant"
    / "web"
)


def _read(name: str) -> str:
    return (WEB_ROOT / name).read_text(encoding="utf-8")


def test_frontend_uses_only_same_origin_local_assets() -> None:
    combined = "\n".join(
        _read(name)
        for name in ("index.html", "styles.css", "app.js")
    )

    assert "http://" not in combined
    assert "https://" not in combined
    assert 'href="/static/styles.css"' in combined
    assert 'src="/static/app.js"' in combined


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
    assert "Try example draft" in html
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


def test_frontend_makes_the_product_boundary_visible() -> None:
    html = _read("index.html")

    for disclosure in (
        "Experimental development candidate",
        "Picks only",
        "Completed drafts",
        "No hero recommendations",
        "not readiness-approved",
        "Association is not causation",
        "No live Liquipedia calls",
    ):
        assert disclosure in html

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
    assert 'event.key === "ArrowDown"' in script
    assert "prefers-reduced-motion: reduce" in styles
