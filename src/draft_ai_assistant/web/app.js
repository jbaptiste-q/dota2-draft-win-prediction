(() => {
  "use strict";

  const HERO_ENDPOINT = "/api/v1/heroes";
  const ANALYZE_ENDPOINT = "/api/v1/analyze";
  const REPLACEMENT_ENDPOINT = "/api/v1/replacement-comparisons";
  const MODEL_CARD_ENDPOINT = "/api/v1/model-card";
  // Replaceable presentation-only artwork path. Every art set follows the
  // frozen hero_key filename contract and retains an accessible initials
  // fallback, so artwork can change without touching product or inference.
  const HERO_PORTRAIT_BASE_PATH = "/static/heroes";
  const PICKS_PER_SIDE = 5;
  const SIDES = ["radiant", "dire"];
  const ATTRIBUTE_FILTERS = ["all", "str", "agi", "int", "universal"];
  const EXAMPLE_DRAFT = Object.freeze({
    radiant: Object.freeze(["axe", "puck", "lina", "tusk", "luna"]),
    dire: Object.freeze(["doom", "invoker", "tiny", "phoenix", "slark"]),
  });
  const FACTION_ART_PREVIEWS = Object.freeze({
    radiant: Object.freeze({
      hero_key: "anti-mage",
      display_name: "Anti-Mage",
    }),
    dire: Object.freeze({
      hero_key: "invoker",
      display_name: "Invoker",
    }),
  });

  // Local, frontend-only presentation metadata (primary attribute per hero).
  // Not part of the API contract — used purely for portrait accent color and
  // the hero-picker attribute filter. Keyed by the frozen catalog hero_key.
  const HERO_ATTRIBUTES = Object.freeze({
    "abaddon":"universal","alchemist":"str","ancient-apparition":"int","anti-mage":"agi",
    "arc-warden":"universal","axe":"str","bane":"universal","batrider":"universal",
    "beastmaster":"universal","bloodseeker":"agi","bounty-hunter":"agi",
    "brewmaster":"universal","bristleback":"str","broodmother":"agi","centaur-warrunner":"str",
    "chaos-knight":"str","chen":"int","clinkz":"agi","clockwerk":"str","crystal-maiden":"int",
    "dark-seer":"int","dark-willow":"int","dawnbreaker":"str","dazzle":"universal",
    "death-prophet":"universal","disruptor":"int","doom":"str","dragon-knight":"str",
    "drow-ranger":"agi","earth-spirit":"str","earthshaker":"str","elder-titan":"str",
    "ember-spirit":"agi","enchantress":"int","enigma":"universal","faceless-void":"agi",
    "grimstroke":"int","gyrocopter":"agi","hoodwink":"agi","huskar":"str","invoker":"int",
    "io":"universal","jakiro":"int","juggernaut":"agi","keeper-of-the-light":"int",
    "kunkka":"str","legion-commander":"str","leshrac":"int","lich":"int","lifestealer":"str",
    "lina":"int","lion":"int","lone-druid":"agi","luna":"agi","lycan":"str",
    "magnus":"universal","marci":"universal","mars":"str","medusa":"agi","meepo":"agi",
    "mirana":"agi","monkey-king":"agi","morphling":"agi","muerta":"int","naga-siren":"agi",
    "nature-s-prophet":"universal","necrophos":"int","night-stalker":"str",
    "nyx-assassin":"universal","ogre-magi":"str","omniknight":"str","oracle":"int",
    "outworld-destroyer":"int","pangolier":"universal","phantom-assassin":"agi",
    "phantom-lancer":"agi","phoenix":"str","primal-beast":"str","puck":"int","pudge":"str",
    "pugna":"int","queen-of-pain":"int","razor":"agi","riki":"agi","ringmaster":"int",
    "rubick":"int","sand-king":"universal","shadow-demon":"int","shadow-fiend":"agi",
    "shadow-shaman":"int","silencer":"int","skywrath-mage":"int","slardar":"str","slark":"agi",
    "snapfire":"universal","sniper":"agi","spectre":"agi","spirit-breaker":"str",
    "storm-spirit":"int","sven":"str","techies":"universal","templar-assassin":"agi",
    "terrorblade":"agi","tidehunter":"str","timbersaw":"str","tinker":"int","tiny":"str",
    "treant-protector":"str","troll-warlord":"agi","tusk":"str","underlord":"str",
    "undying":"str","ursa":"agi","vengeful-spirit":"agi","venomancer":"universal","viper":"agi",
    "visage":"universal","void-spirit":"universal","warlock":"int","weaver":"agi",
    "windranger":"universal","winter-wyvern":"int","witch-doctor":"int","wraith-king":"str",
    "zeus":"int",
  });

  function heroAttribute(heroKey) {
    return HERO_ATTRIBUTES[heroKey] || "";
  }

  const state = {
    heroes: [],
    picks: {
      radiant: Array(PICKS_PER_SIDE).fill(null),
      dire: Array(PICKS_PER_SIDE).fill(null),
    },
    activeSlot: null,
    attributeFilter: "all",
    analyzing: false,
    comparing: false,
    draftRevision: 0,
    comparisonRevision: 0,
    lastAnalysis: null,
  };

  const elements = {
    radiantSlots: document.querySelector("#radiant-slots"),
    direSlots: document.querySelector("#dire-slots"),
    factionShowcases: {
      radiant: {
        root: document.querySelector("#radiant-showcase"),
        art: document.querySelector("#radiant-featured-art"),
        kicker: document.querySelector("#radiant-featured-kicker"),
        name: document.querySelector("#radiant-featured-name"),
      },
      dire: {
        root: document.querySelector("#dire-showcase"),
        art: document.querySelector("#dire-featured-art"),
        kicker: document.querySelector("#dire-featured-kicker"),
        name: document.querySelector("#dire-featured-name"),
      },
    },
    radiantCount: document.querySelector("#radiant-count"),
    direCount: document.querySelector("#dire-count"),
    draftProgress: document.querySelector("#draft-progress"),
    pickTally: document.querySelector(".pick-tally"),
    tallyDots: Array.from(document.querySelectorAll(".tally-dot")),
    resetDraft: document.querySelector("#reset-draft"),
    tryExample: document.querySelector("#try-example"),
    analyzeDraft: document.querySelector("#analyze-draft"),
    analysisError: document.querySelector("#analysis-error"),
    heroDataStatus: document.querySelector("#hero-data-status"),
    picker: document.querySelector("#hero-picker"),
    pickerTitle: document.querySelector("#picker-title"),
    pickerKicker: document.querySelector("#picker-kicker"),
    pickerSummary: document.querySelector("#picker-summary"),
    pickerEmpty: document.querySelector("#picker-empty"),
    closePicker: document.querySelector("#close-picker"),
    heroSearch: document.querySelector("#hero-search"),
    heroOptions: document.querySelector("#hero-options"),
    attributeFilters: document.querySelector("#attribute-filters"),
    resultEmpty: document.querySelector("#result-empty"),
    resultLoading: document.querySelector("#result-loading"),
    resultContent: document.querySelector("#result-content"),
    completedResultTitle: document.querySelector("#completed-result-title"),
    probabilityBar: document.querySelector("#probability-bar"),
    radiantProbability: document.querySelector("#radiant-probability"),
    direProbability: document.querySelector("#dire-probability"),
    outcomeVerdict: document.querySelector("#outcome-verdict"),
    outcomeHeroes: {
      radiant: {
        art: document.querySelector("#outcome-radiant-art"),
        name: document.querySelector("#outcome-radiant-name"),
      },
      dire: {
        art: document.querySelector("#outcome-dire-art"),
        name: document.querySelector("#outcome-dire-name"),
      },
    },
    contributionList: document.querySelector("#contribution-list"),
    limitationsList: document.querySelector("#limitations-list"),
    modelStatus: document.querySelector("#model-status"),
    modelCandidate: document.querySelector("#model-candidate"),
    modelCutoff: document.querySelector("#model-cutoff"),
    modelReadiness: document.querySelector("#model-readiness"),
    modelLockedTest: document.querySelector("#model-locked-test"),
    modelCardStatus: document.querySelector("#model-card-status"),
    evidenceCandidateLogLoss: document.querySelector(
      "#evidence-candidate-log-loss",
    ),
    evidenceReferenceLogLoss: document.querySelector(
      "#evidence-reference-log-loss",
    ),
    evidenceCandidateBrier: document.querySelector(
      "#evidence-candidate-brier",
    ),
    evidenceReferenceBrier: document.querySelector(
      "#evidence-reference-brier",
    ),
    evidenceGate: document.querySelector("#evidence-gate"),
    evidenceLocked: document.querySelector("#evidence-locked"),
    evidenceCutoff: document.querySelector("#evidence-cutoff"),
    replacementSide: document.querySelector("#replacement-side"),
    replacementOutgoing: document.querySelector("#replacement-outgoing"),
    replacementIncoming: document.querySelector("#replacement-incoming"),
    compareReplacement: document.querySelector("#compare-replacement"),
    replacementStatus: document.querySelector("#replacement-status"),
    replacementOutput: document.querySelector("#replacement-output"),
    replacementOutgoingName: document.querySelector(
      "#replacement-outgoing-name",
    ),
    replacementIncomingName: document.querySelector(
      "#replacement-incoming-name",
    ),
    replacementSideLabel: document.querySelector("#replacement-side-label"),
    replacementBaselineProbability: document.querySelector(
      "#replacement-baseline-probability",
    ),
    replacementScenarioProbability: document.querySelector(
      "#replacement-scenario-probability",
    ),
    replacementProbabilityDelta: document.querySelector(
      "#replacement-probability-delta",
    ),
  };

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function titleCase(value) {
    return String(value ?? "")
      .replaceAll("_", " ")
      .replaceAll("-", " ")
      .replace(/\b\w/g, (character) => character.toUpperCase());
  }

  function heroInitials(displayName) {
    const words = String(displayName)
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (words.length === 0) {
      return "?";
    }
    if (words.length === 1) {
      return words[0].slice(0, 2).toUpperCase();
    }
    return `${words[0][0]}${words.at(-1)[0]}`.toUpperCase();
  }

  function heroPortraitSource(heroKey) {
    return (
      `${HERO_PORTRAIT_BASE_PATH}/` +
      `${encodeURIComponent(heroKey)}.webp`
    );
  }

  function heroPortraitMarkup(hero) {
    const attribute = heroAttribute(hero.hero_key);
    const initials = escapeHtml(heroInitials(hero.display_name));
    const source = heroPortraitSource(hero.hero_key);
    return `
      <span class="hero-portrait" data-attr="${escapeHtml(attribute)}">
        <img
          class="hero-portrait-img"
          src="${source}"
          alt=""
          loading="lazy"
          decoding="async"
          width="72"
          height="72"
        >
        <span class="hero-portrait-fallback" aria-hidden="true">${initials}</span>
      </span>
    `;
  }

  function handlePortraitLoadError(event) {
    const target = event.target;
    if (target instanceof HTMLImageElement &&
        (
          target.classList.contains("hero-portrait-img") ||
          target.classList.contains("hero-art-img")
        )) {
      target.hidden = true;
    }
  }

  function selectedHeroKeys(exceptSlot = null) {
    const selected = new Set();
    for (const side of SIDES) {
      state.picks[side].forEach((hero, index) => {
        const excluded =
          exceptSlot &&
          exceptSlot.side === side &&
          exceptSlot.index === index;
        if (hero && !excluded) {
          selected.add(hero.hero_key);
        }
      });
    }
    return selected;
  }

  function selectedCount(side) {
    return state.picks[side].filter(Boolean).length;
  }

  function completeDraft() {
    return SIDES.every(
      (side) => selectedCount(side) === PICKS_PER_SIDE,
    );
  }

  function renderSlot(side, hero, index) {
    const number = String(index + 1).padStart(2, "0");
    const sideName = titleCase(side);
    const disabled = state.analyzing || state.comparing ? "disabled" : "";
    if (!hero) {
      return `
        <div class="pick-slot" data-side="${side}" data-index="${index}">
          <button
            class="slot-select"
            type="button"
            data-action="select"
            aria-haspopup="dialog"
            aria-label="Choose ${sideName} hero ${index + 1}"
            ${disabled}
          >
            <span class="slot-number" aria-hidden="true">${number}</span>
            <span class="slot-copy">
              <strong>Choose hero</strong>
              <span>Empty ${side} pick</span>
            </span>
          </button>
        </div>
      `;
    }

    const displayName = escapeHtml(hero.display_name);
    const heroKey = escapeHtml(hero.hero_key);
    return `
      <div
        class="pick-slot is-filled"
        data-side="${side}"
        data-index="${index}"
      >
        <button
          class="slot-select"
          type="button"
          data-action="select"
          aria-haspopup="dialog"
          aria-label="Change ${sideName} hero ${index + 1}, currently ${displayName}"
          ${disabled}
        >
          ${heroPortraitMarkup(hero)}
          <span class="slot-copy">
            <strong>${displayName}</strong>
            <span>${heroKey}</span>
          </span>
        </button>
        <button
          class="clear-pick"
          type="button"
          data-action="clear"
          aria-label="Remove ${displayName} from ${sideName}"
          ${disabled}
        >×</button>
      </div>
    `;
  }

  function renderPickTally() {
    const order = [...state.picks.radiant, ...state.picks.dire];
    elements.tallyDots.forEach((dot, index) => {
      dot.classList.toggle("is-filled", Boolean(order[index]));
    });
    const filled = order.filter(Boolean).length;
    if (elements.pickTally) {
      elements.pickTally.setAttribute(
        "aria-label",
        `${filled} of ${PICKS_PER_SIDE * 2} heroes selected`,
      );
    }
  }

  function renderFactionShowcase(side) {
    const showcase = elements.factionShowcases[side];
    const selected = [...state.picks[side]].reverse().find(Boolean);
    const hero = selected || FACTION_ART_PREVIEWS[side];
    showcase.root.classList.toggle("is-preview", !selected);
    showcase.art.hidden = false;
    showcase.art.src = heroPortraitSource(hero.hero_key);
    showcase.kicker.textContent = selected
      ? "Lineup focus"
      : "Faction art preview";
    showcase.name.textContent = hero.display_name;
  }

  function renderDraft() {
    elements.radiantSlots.innerHTML = state.picks.radiant
      .map((hero, index) => renderSlot("radiant", hero, index))
      .join("");
    elements.direSlots.innerHTML = state.picks.dire
      .map((hero, index) => renderSlot("dire", hero, index))
      .join("");
    renderFactionShowcase("radiant");
    renderFactionShowcase("dire");

    const radiantCount = selectedCount("radiant");
    const direCount = selectedCount("dire");
    const total = radiantCount + direCount;
    elements.radiantCount.textContent = `${radiantCount} / ${PICKS_PER_SIDE}`;
    elements.direCount.textContent = `${direCount} / ${PICKS_PER_SIDE}`;
    elements.draftProgress.textContent =
      `${total} of ${PICKS_PER_SIDE * 2} heroes selected`;
    renderPickTally();
    elements.analyzeDraft.disabled =
      !completeDraft() ||
      state.analyzing ||
      state.comparing ||
      state.heroes.length === 0;
    elements.resetDraft.disabled = state.analyzing || state.comparing;
    elements.tryExample.disabled =
      state.analyzing || state.comparing || state.heroes.length === 0;
  }

  function clearReplacementOutput() {
    elements.replacementOutput.hidden = true;
    elements.replacementOutgoingName.textContent = "—";
    elements.replacementIncomingName.textContent = "—";
    elements.replacementSideLabel.textContent = "—";
    elements.replacementBaselineProbability.textContent = "—";
    elements.replacementScenarioProbability.textContent = "—";
    elements.replacementProbabilityDelta.textContent = "—";
    elements.replacementProbabilityDelta.className = "";
  }

  function setReplacementStatus(message, kind = "") {
    elements.replacementStatus.textContent = message;
    elements.replacementStatus.className = "replacement-status";
    if (kind) {
      elements.replacementStatus.classList.add(`is-${kind}`);
    }
  }

  function disableReplacementControls() {
    elements.replacementSide.disabled = true;
    elements.replacementOutgoing.disabled = true;
    elements.replacementIncoming.disabled = true;
    elements.compareReplacement.disabled = true;
  }

  function invalidateReplacementExplorer() {
    state.lastAnalysis = null;
    state.comparing = false;
    state.comparisonRevision += 1;
    elements.compareReplacement.classList.remove("is-loading");
    elements.compareReplacement.querySelector(
      "span:first-child",
    ).textContent = "Compare what-if";
    disableReplacementControls();
    elements.replacementSide.value = "radiant";
    elements.replacementOutgoing.replaceChildren();
    elements.replacementIncoming.innerHTML =
      '<option value="">Choose an unselected hero</option>';
    clearReplacementOutput();
    setReplacementStatus(
      "Analyze a completed draft to enable this comparison.",
    );
  }

  function invalidateResult() {
    state.draftRevision += 1;
    invalidateReplacementExplorer();
    elements.resultContent.hidden = true;
    elements.resultLoading.hidden = true;
    elements.resultEmpty.hidden = false;
    elements.analysisError.textContent = "";
  }

  function handleSlotClick(event) {
    const button = event.target.closest("button[data-action]");
    if (!button) {
      return;
    }
    const slot = button.closest(".pick-slot");
    if (!slot) {
      return;
    }
    const side = slot.dataset.side;
    const index = Number(slot.dataset.index);
    if (!SIDES.includes(side) || !Number.isInteger(index)) {
      return;
    }

    if (button.dataset.action === "clear") {
      state.picks[side][index] = null;
      invalidateResult();
      renderDraft();
      return;
    }
    openHeroPicker(side, index);
  }

  function setAttributeFilter(attribute) {
    state.attributeFilter = attribute;
    if (elements.attributeFilters) {
      elements.attributeFilters
        .querySelectorAll(".attr-filter")
        .forEach((button) => {
          const isActive = button.dataset.attr === attribute;
          button.classList.toggle("is-active", isActive);
          button.setAttribute("aria-pressed", String(isActive));
        });
    }
    renderHeroOptions();
  }

  function openHeroPicker(side, index) {
    if (state.heroes.length === 0) {
      elements.analysisError.textContent =
        "The hero catalog is unavailable. Refresh the page to try again.";
      return;
    }
    state.activeSlot = { side, index };
    elements.pickerKicker.textContent =
      side === "radiant" ? "The Radiant" : "The Dire";
    elements.pickerTitle.textContent =
      `Choose ${titleCase(side)} pick ${index + 1}`;
    elements.heroSearch.value = "";
    setAttributeFilter("all");
    elements.picker.showModal();
    window.requestAnimationFrame(() => elements.heroSearch.focus());
  }

  function closeHeroPicker() {
    if (elements.picker.open) {
      elements.picker.close();
    }
  }

  function renderHeroOptions() {
    const query = elements.heroSearch.value.trim().toLocaleLowerCase();
    const selected = selectedHeroKeys(state.activeSlot);
    const filtered = state.heroes.filter((hero) => {
      if (
        state.attributeFilter !== "all" &&
        heroAttribute(hero.hero_key) !== state.attributeFilter
      ) {
        return false;
      }
      if (!query) {
        return true;
      }
      return (
        hero.display_name.toLocaleLowerCase().includes(query) ||
        hero.hero_key.toLocaleLowerCase().includes(query)
      );
    });

    elements.pickerSummary.textContent =
      `${filtered.length} ${filtered.length === 1 ? "hero" : "heroes"} shown`;
    elements.pickerEmpty.hidden = filtered.length !== 0;
    elements.heroOptions.innerHTML = filtered
      .map((hero) => {
        const isSelected = selected.has(hero.hero_key);
        const displayName = escapeHtml(hero.display_name);
        return `
          <button
            class="hero-option"
            type="button"
            data-hero-key="${escapeHtml(hero.hero_key)}"
            ${isSelected ? "disabled" : ""}
            aria-label="${
              isSelected
                ? `${displayName} is already selected`
                : `Select ${displayName}`
            }"
          >
            ${heroPortraitMarkup(hero)}
            <span>
              <strong>${displayName}</strong>
              <span>${escapeHtml(
                isSelected ? "Already selected" : hero.hero_key,
              )}</span>
            </span>
          </button>
        `;
      })
      .join("");
  }

  function heroOptionGridColumns() {
    const template = window
      .getComputedStyle(elements.heroOptions)
      .gridTemplateColumns.trim();
    if (!template) {
      return 1;
    }
    return template.split(/\s+/).length;
  }

  function navigateHeroOptions(event) {
    const options = Array.from(
      elements.heroOptions.querySelectorAll(
        "button.hero-option:not(:disabled)",
      ),
    );
    if (options.length === 0) {
      return;
    }
    const focused = document.activeElement;
    const currentIndex = options.indexOf(focused);
    const columns = heroOptionGridColumns();
    let nextIndex = null;

    switch (event.key) {
      case "ArrowRight":
        nextIndex = currentIndex === -1 ? 0 : currentIndex + 1;
        break;
      case "ArrowLeft":
        nextIndex = currentIndex === -1 ? 0 : currentIndex - 1;
        break;
      case "ArrowDown":
        nextIndex = currentIndex === -1 ? 0 : currentIndex + columns;
        break;
      case "ArrowUp":
        nextIndex = currentIndex === -1 ? 0 : currentIndex - columns;
        break;
      case "Home":
        nextIndex = 0;
        break;
      case "End":
        nextIndex = options.length - 1;
        break;
      default:
        return;
    }

    event.preventDefault();
    nextIndex = Math.max(0, Math.min(options.length - 1, nextIndex));
    options[nextIndex]?.focus();
  }

  function chooseHero(event) {
    const button = event.target.closest("button[data-hero-key]");
    if (!button || button.disabled || !state.activeSlot) {
      return;
    }
    const hero = state.heroes.find(
      (candidate) => candidate.hero_key === button.dataset.heroKey,
    );
    if (!hero) {
      return;
    }
    const { side, index } = state.activeSlot;
    if (selectedHeroKeys(state.activeSlot).has(hero.hero_key)) {
      return;
    }
    state.picks[side][index] = hero;
    invalidateResult();
    renderDraft();
    closeHeroPicker();

    let nextSide = side;
    let nextIndex = state.picks[nextSide].findIndex(
      (value) => value === null,
    );
    if (nextIndex === -1) {
      nextSide = side === "radiant" ? "dire" : "radiant";
      nextIndex = state.picks[nextSide].findIndex(
        (value) => value === null,
      );
    }
    if (nextIndex !== -1) {
      const nextButton = document.querySelector(
        `.pick-slot[data-side="${nextSide}"][data-index="${nextIndex}"] ` +
          `.slot-select`,
      );
      nextButton?.focus();
    } else {
      elements.analyzeDraft.focus();
    }
  }

  function setHeroStatus(message, kind = "") {
    elements.heroDataStatus.textContent = message;
    elements.heroDataStatus.className = "data-status";
    if (kind) {
      elements.heroDataStatus.classList.add(`is-${kind}`);
    }
  }

  function validateHeroPayload(payload) {
    if (payload?.schema_version !== "draft-assistant-heroes-v1") {
      throw new Error("Hero catalog schema version is unsupported.");
    }
    const values = payload && Array.isArray(payload.heroes)
      ? payload.heroes
      : null;
    if (!values || values.length === 0) {
      throw new Error("Hero catalog response did not contain any heroes.");
    }
    if (Number(payload.count) !== values.length) {
      throw new Error("Hero catalog count does not match its records.");
    }

    const seen = new Set();
    const heroes = values.map((value) => {
      const heroKey = String(value?.hero_key ?? "").trim();
      const displayName = String(value?.display_name ?? "").trim();
      if (!heroKey || !displayName || seen.has(heroKey)) {
        throw new Error("Hero catalog response is malformed.");
      }
      seen.add(heroKey);
      return { hero_key: heroKey, display_name: displayName };
    });
    return heroes.sort((left, right) =>
      left.display_name.localeCompare(right.display_name),
    );
  }

  async function loadHeroes() {
    setHeroStatus("Loading hero catalog");
    try {
      const response = await fetch(HERO_ENDPOINT, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`Hero catalog returned HTTP ${response.status}.`);
      }
      state.heroes = validateHeroPayload(await response.json());
      setHeroStatus(`${state.heroes.length} heroes ready`, "ready");
    } catch (error) {
      console.error(error);
      setHeroStatus("Hero catalog unavailable", "error");
      elements.analysisError.textContent =
        "Could not load the hero catalog. Refresh the page to try again.";
    }
    renderDraft();
  }

  function evidenceMetric(value, label) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0) {
      throw new Error(`${label} is invalid.`);
    }
    return parsed.toFixed(6);
  }

  function setModelCardStatus(message, kind = "") {
    elements.modelCardStatus.textContent = message;
    elements.modelCardStatus.className = "model-card-status";
    if (kind) {
      elements.modelCardStatus.classList.add(`is-${kind}`);
    }
  }

  function renderModelCard(payload) {
    if (payload?.schema_version !== "draft-assistant-model-card-v1") {
      throw new Error("Model-card schema version is unsupported.");
    }
    const evaluation = payload.evaluation;
    const candidate = evaluation?.candidate;
    const reference = evaluation?.reference_metrics;
    const evaluationRows = Number(evaluation?.rows);
    if (
      !candidate ||
      !reference ||
      !payload.fit ||
      evaluation?.period !== "2025-Q4" ||
      !Number.isInteger(evaluationRows) ||
      evaluationRows < 1
    ) {
      throw new Error("Model-card evidence is incomplete.");
    }

    elements.evidenceCandidateLogLoss.textContent = evidenceMetric(
      candidate.log_loss,
      "Candidate log loss",
    );
    elements.evidenceReferenceLogLoss.textContent = evidenceMetric(
      reference.log_loss,
      "Reference log loss",
    );
    elements.evidenceCandidateBrier.textContent = evidenceMetric(
      candidate.brier_score,
      "Candidate Brier score",
    );
    elements.evidenceReferenceBrier.textContent = evidenceMetric(
      reference.brier_score,
      "Reference Brier score",
    );

    const readinessPassed = evaluation.readiness_gate_passed === true;
    elements.evidenceGate.textContent = readinessPassed ? "Passed" : "Failed";
    elements.evidenceGate.classList.toggle(
      "is-negative",
      !readinessPassed,
    );

    const lockedEvaluated = evaluation.locked_test_evaluated === true;
    elements.evidenceLocked.textContent = lockedEvaluated
      ? "Evaluated"
      : "Not evaluated";
    elements.evidenceLocked.classList.toggle(
      "is-negative",
      !lockedEvaluated,
    );
    elements.evidenceCutoff.textContent = formatCutoff(
      payload.fit.cutoff_utc_exclusive,
    );
    setModelCardStatus(
      `${evaluation.period} evidence · ${evaluationRows.toLocaleString()} games`,
      "ready",
    );
  }

  async function loadModelCard() {
    setModelCardStatus("Loading evaluation evidence");
    try {
      const response = await fetch(MODEL_CARD_ENDPOINT, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`Model card returned HTTP ${response.status}.`);
      }
      renderModelCard(await response.json());
    } catch (error) {
      console.error(error);
      setModelCardStatus(
        "Evidence unavailable; draft analysis remains available.",
        "error",
      );
      elements.evidenceGate.textContent = "Unavailable";
      elements.evidenceLocked.textContent = "Unavailable";
      elements.evidenceCutoff.textContent = "Unavailable";
    }
  }

  function setAnalyzing(value) {
    state.analyzing = value;
    elements.analyzeDraft.classList.toggle("is-loading", value);
    elements.analyzeDraft.querySelector("span:first-child").textContent = value
      ? "Resolving the draft"
      : "Resolve the draft";
    if (value) {
      elements.resultEmpty.hidden = true;
      elements.resultLoading.hidden = false;
      elements.resultContent.hidden = true;
    } else {
      elements.resultLoading.hidden = true;
    }
    renderDraft();
  }

  function parseProbability(value, label) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0 || parsed > 1) {
      throw new Error(`${label} probability is invalid.`);
    }
    return parsed;
  }

  function formatProbability(value) {
    return new Intl.NumberFormat(undefined, {
      style: "percent",
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }).format(value);
  }

  function renderOutcomeBattle(
    contributions,
    analyzedDraft,
    radiant,
    dire,
  ) {
    for (const side of SIDES) {
      const featured = contributions.find((item) => item.side === side);
      const fallbackKey =
        analyzedDraft[`${side}_picks`][0];
      const heroKey = featured?.hero_key || fallbackKey;
      const hero = state.heroes.find((item) => item.hero_key === heroKey);
      const displayName =
        featured?.display_name || hero?.display_name || titleCase(heroKey);
      const outcomeHero = elements.outcomeHeroes[side];
      outcomeHero.art.hidden = false;
      outcomeHero.art.src = heroPortraitSource(heroKey);
      outcomeHero.name.textContent = displayName;
    }

    const difference = radiant - dire;
    const leadingSide =
      Math.abs(difference) < 0.001
        ? null
        : difference > 0
          ? "radiant"
          : "dire";
    elements.outcomeVerdict.textContent = leadingSide
      ? `${titleCase(leadingSide)} advantage`
      : "Even draft";
    elements.outcomeVerdict.classList.toggle(
      "is-radiant",
      leadingSide === "radiant",
    );
    elements.outcomeVerdict.classList.toggle(
      "is-dire",
      leadingSide === "dire",
    );
  }

  function currentDraftRequest() {
    return {
      radiant_picks: state.picks.radiant.map((hero) => hero.hero_key),
      dire_picks: state.picks.dire.map((hero) => hero.hero_key),
    };
  }

  function copyDraftRequest(draft) {
    return {
      radiant_picks: [...draft.radiant_picks],
      dire_picks: [...draft.dire_picks],
    };
  }

  function normalizedDraftEcho(value, label) {
    if (
      value?.representation !==
      "unordered_side_relative_completed_picks"
    ) {
      throw new Error(`${label} draft representation is unsupported.`);
    }
    const draft = {};
    for (const field of ["radiant_picks", "dire_picks"]) {
      if (
        !Array.isArray(value[field]) ||
        value[field].length !== PICKS_PER_SIDE
      ) {
        throw new Error(`${label} draft is incomplete.`);
      }
      const picks = value[field].map((heroKey) => String(heroKey ?? "").trim());
      if (
        picks.some((heroKey) => !heroKey) ||
        new Set(picks).size !== PICKS_PER_SIDE
      ) {
        throw new Error(`${label} draft contains invalid hero keys.`);
      }
      draft[field] = picks;
    }
    if (
      new Set([...draft.radiant_picks, ...draft.dire_picks]).size !==
      PICKS_PER_SIDE * 2
    ) {
      throw new Error(`${label} draft repeats a hero across sides.`);
    }
    return draft;
  }

  function draftMatches(actual, expected) {
    return ["radiant_picks", "dire_picks"].every((field) => {
      const left = [...actual[field]].sort();
      const right = [...expected[field]].sort();
      return left.length === right.length &&
        left.every((heroKey, index) => heroKey === right[index]);
    });
  }

  function replacementDraft(draft, side, outgoing, incoming) {
    const result = copyDraftRequest(draft);
    const field = `${side}_picks`;
    const index = result[field].indexOf(outgoing);
    if (index === -1) {
      throw new Error("The outgoing hero is not present on the selected side.");
    }
    result[field][index] = incoming;
    return result;
  }

  function formatSignedPercentagePoints(value) {
    const points = value * 100;
    const normalized = Math.abs(points) < 0.05 ? 0 : points;
    return `${normalized > 0 ? "+" : ""}${normalized.toFixed(1)} pp`;
  }

  function formatCutoff(value) {
    if (!value) {
      return "Not supplied";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value);
    }
    return `${new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    }).format(date)} UTC`;
  }

  function formatSupports(value) {
    const normalized = String(value ?? "").toLocaleLowerCase();
    if (normalized === "radiant" || normalized === "dire") {
      return `Supports ${titleCase(normalized)}`;
    }
    if (normalized === "neutral") {
      return "Neutral contribution";
    }
    return "Direction unavailable";
  }

  function normalizedContributions(payload) {
    const values = payload?.explanation?.contributions;
    if (!Array.isArray(values) || values.length === 0) {
      throw new Error("Explanation contributions are unavailable.");
    }
    return values
      .map((value) => {
        const coefficient = Number(value?.coefficient_log_odds);
        const side = String(value?.side ?? "").toLocaleLowerCase();
        if (
          !Number.isFinite(coefficient) ||
          !SIDES.includes(side) ||
          !value?.hero_key
        ) {
          throw new Error("Explanation contribution is malformed.");
        }
        return {
          hero_key: String(value.hero_key),
          display_name: String(value.display_name || value.hero_key),
          side,
          coefficient_log_odds: coefficient,
          supports: value.supports,
        };
      })
      .sort((left, right) => {
        const magnitude =
          Math.abs(right.coefficient_log_odds) -
          Math.abs(left.coefficient_log_odds);
        if (magnitude !== 0) {
          return magnitude;
        }
        return left.display_name.localeCompare(right.display_name);
      });
  }

  function renderContributions(contributions) {
    const maximum = Math.max(
      ...contributions.map((item) => Math.abs(item.coefficient_log_odds)),
      Number.EPSILON,
    );
    elements.contributionList.innerHTML = contributions
      .map((item) => {
        const coefficient = item.coefficient_log_odds;
        const impact = coefficient >= 0 ? "radiant" : "dire";
        const width = Math.max(4, (Math.abs(coefficient) / maximum) * 100);
        const formatted = `${coefficient >= 0 ? "+" : ""}${coefficient.toFixed(
          4,
        )}`;
        return `
          <li
            class="contribution-row"
            data-side="${item.side}"
            data-impact="${impact}"
            style="--impact-width: ${width.toFixed(2)}%"
          >
            ${heroPortraitMarkup({
              hero_key: item.hero_key,
              display_name: item.display_name,
            })}
            <span class="contribution-hero">
              <strong>${escapeHtml(item.display_name)}</strong>
              <span>${titleCase(item.side)} pick · ${escapeHtml(
                formatSupports(item.supports),
              )}</span>
            </span>
            <span class="impact-track" aria-hidden="true"><span></span></span>
            <span
              class="contribution-value"
              aria-label="${formatted} log odds toward ${titleCase(impact)}"
            >${formatted}</span>
          </li>
        `;
      })
      .join("");
  }

  function renderLimitations(values) {
    const limitations =
      Array.isArray(values) && values.length > 0
        ? values
        : [
            "This development candidate has not passed its readiness gate.",
            "Only completed five-versus-five pick lineups are supported.",
            "The model does not produce hero recommendations.",
          ];
    elements.limitationsList.innerHTML = limitations
      .map((value) => `<li>${escapeHtml(value)}</li>`)
      .join("");
  }

  function renderModel(model) {
    const status = String(model?.status || "experimental_development_candidate");
    elements.modelStatus.textContent = titleCase(status);
    elements.modelCandidate.textContent = String(
      model?.candidate_id || "Not supplied",
    );
    elements.modelCutoff.textContent = formatCutoff(
      model?.fit_cutoff_utc_exclusive,
    );

    const readinessPassed = model?.readiness_gate_passed === true;
    elements.modelReadiness.textContent = readinessPassed
      ? "Passed"
      : "Not passed";
    elements.modelReadiness.classList.toggle(
      "fact-negative",
      !readinessPassed,
    );

    const lockedTestEvaluated = model?.locked_test_evaluated === true;
    elements.modelLockedTest.textContent = lockedTestEvaluated
      ? "Evaluated"
      : "Not evaluated";
    elements.modelLockedTest.classList.toggle(
      "fact-negative",
      !lockedTestEvaluated,
    );
  }

  function heroByKey(heroKey) {
    return state.heroes.find((hero) => hero.hero_key === heroKey) || null;
  }

  function populateReplacementOutgoing() {
    const analysis = state.lastAnalysis;
    if (!analysis) {
      return;
    }
    const side = elements.replacementSide.value;
    const picks = analysis.draft[`${side}_picks`];
    elements.replacementOutgoing.innerHTML = picks
      .map((heroKey) => {
        const hero = heroByKey(heroKey);
        return `
          <option value="${escapeHtml(heroKey)}">
            ${escapeHtml(hero?.display_name || heroKey)}
          </option>
        `;
      })
      .join("");
  }

  function populateReplacementIncoming() {
    const selected = new Set([
      ...state.lastAnalysis.draft.radiant_picks,
      ...state.lastAnalysis.draft.dire_picks,
    ]);
    elements.replacementIncoming.innerHTML = [
      '<option value="">Choose an unselected hero</option>',
      ...state.heroes
        .filter((hero) => !selected.has(hero.hero_key))
        .map(
          (hero) => `
            <option value="${escapeHtml(hero.hero_key)}">
              ${escapeHtml(hero.display_name)}
            </option>
          `,
        ),
    ].join("");
  }

  function updateReplacementButton() {
    elements.compareReplacement.disabled =
      !state.lastAnalysis ||
      state.comparing ||
      !elements.replacementOutgoing.value ||
      !elements.replacementIncoming.value;
  }

  function configureReplacementExplorer() {
    if (!state.lastAnalysis) {
      disableReplacementControls();
      return;
    }
    elements.replacementSide.disabled = state.comparing;
    elements.replacementOutgoing.disabled = state.comparing;
    elements.replacementIncoming.disabled = state.comparing;
    populateReplacementOutgoing();
    populateReplacementIncoming();
    clearReplacementOutput();
    setReplacementStatus(
      "Choose the outgoing and incoming heroes, then compare the two scenarios.",
    );
    updateReplacementButton();
  }

  function replacementSelectionChanged(event) {
    if (!state.lastAnalysis || state.comparing) {
      return;
    }
    state.comparisonRevision += 1;
    clearReplacementOutput();
    if (event.currentTarget === elements.replacementSide) {
      populateReplacementOutgoing();
    }
    setReplacementStatus(
      elements.replacementIncoming.value
        ? "Ready to compare these two completed drafts."
        : "Choose an unselected incoming hero to continue.",
    );
    updateReplacementButton();
  }

  function setComparing(value) {
    state.comparing = value;
    elements.compareReplacement.classList.toggle("is-loading", value);
    elements.compareReplacement.querySelector(
      "span:first-child",
    ).textContent = value ? "Comparing scenarios" : "Compare what-if";
    elements.replacementSide.disabled = value || !state.lastAnalysis;
    elements.replacementOutgoing.disabled = value || !state.lastAnalysis;
    elements.replacementIncoming.disabled = value || !state.lastAnalysis;
    updateReplacementButton();
    renderDraft();
  }

  function normalizedHeroRecord(value, label) {
    const heroKey = String(value?.hero_key ?? "").trim();
    const displayName = String(value?.display_name ?? "").trim();
    if (!heroKey || !displayName) {
      throw new Error(`${label} hero record is malformed.`);
    }
    return { hero_key: heroKey, display_name: displayName };
  }

  function normalizedScenario(value, label) {
    const predictionId = String(value?.prediction_id ?? "").trim();
    if (!predictionId) {
      throw new Error(`${label} prediction identifier is missing.`);
    }
    const draft = normalizedDraftEcho(value?.draft, label);
    const radiant = parseProbability(
      value?.probability?.radiant_win,
      `${label} Radiant`,
    );
    const dire = parseProbability(
      value?.probability?.dire_win,
      `${label} Dire`,
    );
    if (
      value?.probability?.method !== "raw_logistic" ||
      Math.abs(radiant + dire - 1) > 1e-6
    ) {
      throw new Error(`${label} probabilities are incompatible.`);
    }
    return {
      prediction_id: predictionId,
      draft,
      probability: { radiant_win: radiant, dire_win: dire },
    };
  }

  function validateReplacementPayload(payload, request, analysis) {
    if (
      payload?.schema_version !==
      "draft-assistant-replacement-comparison-v1"
    ) {
      throw new Error(
        "Replacement comparison response schema version is unsupported.",
      );
    }
    if (
      payload?.interpretation !==
        "associative_model_comparison_not_causal" ||
      payload?.recommendation !== false
    ) {
      throw new Error("Replacement comparison safeguards are missing.");
    }
    if (
      String(payload?.comparison_id ?? "").trim() === "" ||
      payload?.side !== request.side
    ) {
      throw new Error("Replacement comparison identity is malformed.");
    }

    const outgoing = normalizedHeroRecord(payload?.outgoing, "Outgoing");
    const incoming = normalizedHeroRecord(payload?.incoming, "Incoming");
    if (
      outgoing.hero_key !== request.hero_to_replace ||
      incoming.hero_key !== request.replacement_hero
    ) {
      throw new Error("Replacement comparison does not echo the requested heroes.");
    }

    const baseline = normalizedScenario(payload?.baseline, "Baseline");
    const replacement = normalizedScenario(
      payload?.replacement,
      "Replacement",
    );
    const expectedReplacement = replacementDraft(
      analysis.draft,
      request.side,
      request.hero_to_replace,
      request.replacement_hero,
    );
    if (
      baseline.prediction_id !== analysis.predictionId ||
      !draftMatches(baseline.draft, analysis.draft) ||
      !draftMatches(replacement.draft, expectedReplacement)
    ) {
      throw new Error("Replacement comparison draft echo does not match the request.");
    }

    const delta = {
      radiant_win: Number(payload?.delta?.radiant_win),
      dire_win: Number(payload?.delta?.dire_win),
      selected_side_win: Number(payload?.delta?.selected_side_win),
    };
    if (
      Object.values(delta).some(
        (value) => !Number.isFinite(value) || value < -1 || value > 1,
      )
    ) {
      throw new Error("Replacement comparison deltas are invalid.");
    }
    const expectedRadiant =
      replacement.probability.radiant_win -
      baseline.probability.radiant_win;
    const expectedDire =
      replacement.probability.dire_win -
      baseline.probability.dire_win;
    const expectedSelected =
      request.side === "radiant" ? expectedRadiant : expectedDire;
    if (
      Math.abs(delta.radiant_win - expectedRadiant) > 1e-9 ||
      Math.abs(delta.dire_win - expectedDire) > 1e-9 ||
      Math.abs(delta.selected_side_win - expectedSelected) > 1e-9
    ) {
      throw new Error(
        "Replacement comparison deltas do not reconstruct the scenarios.",
      );
    }
    if (
      payload?.model?.status !== "development_candidate" ||
      payload?.model?.readiness_gate_passed !== false ||
      payload?.model?.locked_test_evaluated !== false ||
      !Array.isArray(payload?.limitations) ||
      payload.limitations.length === 0
    ) {
      throw new Error("Replacement comparison model disclosure is incomplete.");
    }

    return { outgoing, incoming, baseline, replacement, delta };
  }

  function renderReplacementComparison(comparison, side) {
    const baselineProbability =
      comparison.baseline.probability[`${side}_win`];
    const replacementProbability =
      comparison.replacement.probability[`${side}_win`];
    const delta = comparison.delta.selected_side_win;
    elements.replacementOutgoingName.textContent =
      comparison.outgoing.display_name;
    elements.replacementIncomingName.textContent =
      comparison.incoming.display_name;
    elements.replacementSideLabel.textContent = `${titleCase(side)} scenario`;
    elements.replacementBaselineProbability.textContent =
      formatProbability(baselineProbability);
    elements.replacementScenarioProbability.textContent =
      formatProbability(replacementProbability);
    elements.replacementProbabilityDelta.textContent =
      formatSignedPercentagePoints(delta);
    elements.replacementProbabilityDelta.className =
      delta > 0 ? "is-positive" : delta < 0 ? "is-negative" : "is-neutral";
    elements.replacementOutput.hidden = false;
    setReplacementStatus(
      "Comparison complete. The displayed change is a model estimate, not advice.",
      "ready",
    );
  }

  async function compareReplacement() {
    const analysis = state.lastAnalysis;
    if (!analysis || state.comparing) {
      return;
    }
    const request = {
      ...copyDraftRequest(analysis.draft),
      side: elements.replacementSide.value,
      hero_to_replace: elements.replacementOutgoing.value,
      replacement_hero: elements.replacementIncoming.value,
    };
    if (
      !SIDES.includes(request.side) ||
      !request.hero_to_replace ||
      !request.replacement_hero
    ) {
      setReplacementStatus(
        "Choose a side, outgoing hero, and incoming hero.",
        "error",
      );
      return;
    }

    const comparisonRevision = state.comparisonRevision + 1;
    state.comparisonRevision = comparisonRevision;
    clearReplacementOutput();
    setReplacementStatus("Comparing two completed-draft scenarios.");
    setComparing(true);
    try {
      const response = await fetch(REPLACEMENT_ENDPOINT, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(request),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(responseError(payload, response.status));
      }
      const comparison = validateReplacementPayload(
        payload,
        request,
        analysis,
      );
      if (
        comparisonRevision !== state.comparisonRevision ||
        analysis !== state.lastAnalysis ||
        analysis.draftRevision !== state.draftRevision
      ) {
        return;
      }
      renderReplacementComparison(comparison, request.side);
    } catch (error) {
      if (
        comparisonRevision !== state.comparisonRevision ||
        analysis !== state.lastAnalysis
      ) {
        return;
      }
      console.error(error);
      setReplacementStatus(
        error instanceof Error
          ? error.message
          : "The replacement scenarios could not be compared.",
        "error",
      );
    } finally {
      if (
        comparisonRevision === state.comparisonRevision &&
        analysis === state.lastAnalysis
      ) {
        setComparing(false);
      }
    }
  }

  function renderResult(payload, analyzedDraft, draftRevision) {
    if (payload?.schema_version !== "draft-assistant-analysis-v1") {
      throw new Error("Analysis response schema version is unsupported.");
    }
    const predictionId = String(payload?.prediction_id ?? "").trim();
    const echoedDraft = normalizedDraftEcho(payload?.draft, "Analysis");
    if (!predictionId || !draftMatches(echoedDraft, analyzedDraft)) {
      throw new Error("Analysis response does not match the submitted draft.");
    }
    const radiant = parseProbability(
      payload?.probability?.radiant_win,
      "Radiant",
    );
    const dire = parseProbability(payload?.probability?.dire_win, "Dire");
    if (Math.abs(radiant + dire - 1) > 1e-6) {
      throw new Error("Side probabilities do not sum to one.");
    }

    const contributions = normalizedContributions(payload);
    elements.radiantProbability.textContent = formatProbability(radiant);
    elements.direProbability.textContent = formatProbability(dire);
    elements.probabilityBar.style.setProperty(
      "--radiant-share",
      `${(radiant * 100).toFixed(4)}%`,
    );
    elements.probabilityBar.setAttribute(
      "aria-label",
      `Radiant ${formatProbability(radiant)}, Dire ${formatProbability(dire)}`,
    );
    renderOutcomeBattle(contributions, analyzedDraft, radiant, dire);
    renderContributions(contributions);
    renderModel(payload?.model || payload);
    renderLimitations(payload?.limitations);
    state.lastAnalysis = {
      draft: copyDraftRequest(analyzedDraft),
      predictionId,
      draftRevision,
    };
    configureReplacementExplorer();

    elements.resultLoading.hidden = true;
    elements.resultEmpty.hidden = true;
    elements.resultContent.hidden = false;
    elements.completedResultTitle.focus({ preventScroll: true });
    elements.resultContent.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
      block: "start",
    });
  }

  function responseError(payload, status) {
    const detail = payload?.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (
      detail &&
      typeof detail === "object" &&
      typeof detail.message === "string"
    ) {
      return detail.message;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      return detail
        .map((item) => item?.msg)
        .filter(Boolean)
        .join("; ");
    }
    return `Analysis request failed with HTTP ${status}.`;
  }

  async function analyzeDraft() {
    if (!completeDraft() || state.analyzing || state.comparing) {
      return;
    }
    const allKeys = SIDES.flatMap((side) =>
      state.picks[side].map((hero) => hero.hero_key),
    );
    if (new Set(allKeys).size !== PICKS_PER_SIDE * 2) {
      elements.analysisError.textContent =
        "Each hero may appear only once in a completed draft.";
      return;
    }

    elements.analysisError.textContent = "";
    const analyzedDraft = currentDraftRequest();
    const draftRevision = state.draftRevision;
    invalidateReplacementExplorer();
    setAnalyzing(true);
    try {
      const response = await fetch(ANALYZE_ENDPOINT, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(analyzedDraft),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(responseError(payload, response.status));
      }
      if (draftRevision !== state.draftRevision) {
        return;
      }
      renderResult(payload, analyzedDraft, draftRevision);
    } catch (error) {
      console.error(error);
      elements.resultLoading.hidden = true;
      elements.resultEmpty.hidden = false;
      elements.analysisError.textContent =
        error instanceof Error
          ? error.message
          : "The draft could not be analyzed.";
    } finally {
      setAnalyzing(false);
    }
  }

  async function tryExampleDraft() {
    if (state.heroes.length === 0 || state.analyzing || state.comparing) {
      return;
    }
    const byKey = new Map(
      state.heroes.map((hero) => [hero.hero_key, hero]),
    );
    const exampleKeys = [...EXAMPLE_DRAFT.radiant, ...EXAMPLE_DRAFT.dire];
    const missing = exampleKeys.filter((heroKey) => !byKey.has(heroKey));
    if (missing.length > 0) {
      elements.analysisError.textContent =
        "The workflow example is unavailable in this hero catalog.";
      return;
    }

    state.picks.radiant = EXAMPLE_DRAFT.radiant.map(
      (heroKey) => byKey.get(heroKey),
    );
    state.picks.dire = EXAMPLE_DRAFT.dire.map(
      (heroKey) => byKey.get(heroKey),
    );
    invalidateResult();
    renderDraft();
    elements.draftProgress.textContent =
      "Example workflow loaded; running analysis";
    await analyzeDraft();
  }

  function resetDraft() {
    if (state.analyzing || state.comparing) {
      return;
    }
    for (const side of SIDES) {
      state.picks[side] = Array(PICKS_PER_SIDE).fill(null);
    }
    invalidateResult();
    renderDraft();
    elements.radiantSlots
      .querySelector(".slot-select")
      ?.focus({ preventScroll: true });
  }

  function bindEvents() {
    elements.radiantSlots.addEventListener("click", handleSlotClick);
    elements.direSlots.addEventListener("click", handleSlotClick);
    elements.resetDraft.addEventListener("click", resetDraft);
    elements.tryExample.addEventListener("click", tryExampleDraft);
    elements.analyzeDraft.addEventListener("click", analyzeDraft);
    elements.replacementSide.addEventListener(
      "change",
      replacementSelectionChanged,
    );
    elements.replacementOutgoing.addEventListener(
      "change",
      replacementSelectionChanged,
    );
    elements.replacementIncoming.addEventListener(
      "change",
      replacementSelectionChanged,
    );
    elements.compareReplacement.addEventListener(
      "click",
      compareReplacement,
    );
    elements.closePicker.addEventListener("click", closeHeroPicker);
    elements.heroSearch.addEventListener("input", renderHeroOptions);
    elements.heroOptions.addEventListener("click", chooseHero);
    elements.heroOptions.addEventListener("keydown", navigateHeroOptions);
    elements.heroSearch.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        elements.heroOptions.querySelector("button:not(:disabled)")?.focus();
      }
    });
    if (elements.attributeFilters) {
      elements.attributeFilters.addEventListener("click", (event) => {
        const button = event.target.closest(".attr-filter");
        if (!button || !ATTRIBUTE_FILTERS.includes(button.dataset.attr)) {
          return;
        }
        setAttributeFilter(button.dataset.attr);
      });
    }
    elements.picker.addEventListener("close", () => {
      state.activeSlot = null;
    });
    document.addEventListener("error", handlePortraitLoadError, true);
  }

  bindEvents();
  invalidateReplacementExplorer();
  renderDraft();
  loadHeroes();
  loadModelCard();
})();
