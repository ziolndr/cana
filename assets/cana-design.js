/* CANA_DESIGN_V1 */
(() => {
  'use strict';

  const q = (selector, root = document) => root.querySelector(selector);
  const qa = (selector, root = document) => [...root.querySelectorAll(selector)];
  const lab = q('#designLab');
  const form = q('#designForm');
  const intent = q('#designIntent');
  const status = q('#designStatus');
  const output = q('#designOutput');
  const submit = q('#designSubmit');
  const exportButton = q('#designExport');
  let latestSpec = null;

  const NATURAL_LIBRARY = [
    {
      name: 'LAVENDER AROMATIC MATRIX',
      source: 'Lavandula angustifolia',
      class: 'AROMATIC BOTANICAL',
      evidence: 'HUMAN EVIDENCE · LIMITED',
      profile: 'soft floral aromatic profile; calm sensory tone; low stimulation; relaxation-associated; linalool-rich volatile architecture; requires sedation and interaction screening',
      markers: ['linalool', 'floral', 'calm', 'low stimulation'],
      guardrail: 'Concentrated oils require identity, purity and route-specific safety review.'
    },
    {
      name: 'HOPS VOLATILE MATRIX',
      source: 'Humulus lupulus',
      class: 'AROMATIC BOTANICAL',
      evidence: 'PRECLINICAL + TRADITIONAL',
      profile: 'earthy resinous aromatic profile; body relaxation; evening context; beta-caryophyllene, humulene and myrcene-associated volatile architecture; may increase heaviness',
      markers: ['earthy', 'body calm', 'evening', 'resinous'],
      guardrail: 'Screen sedation, allergy and medication interactions.'
    },
    {
      name: 'CITRUS PEEL MATRIX',
      source: 'Citrus spp.',
      class: 'AROMATIC BOTANICAL',
      evidence: 'SENSORY + LIMITED HUMAN',
      profile: 'bright citrus aromatic profile; energetic sensory tone; social and daytime context; limonene-rich volatile architecture; low body heaviness',
      markers: ['bright', 'citrus', 'daytime', 'social'],
      guardrail: 'Species, oxidation and phototoxicity risks must be analytically controlled.'
    },
    {
      name: 'BLACK PEPPER MATRIX',
      source: 'Piper nigrum',
      class: 'FOOD-GRADE BOTANICAL',
      evidence: 'MECHANISTIC · LIMITED HUMAN',
      profile: 'dry spicy aromatic profile; grounding sensory character; beta-caryophyllene-rich architecture; low sweetness; useful as a counterweight to bright volatile profiles',
      markers: ['grounding', 'spicy', 'dry', 'balanced'],
      guardrail: 'Screen gastrointestinal tolerance, allergy and drug interactions.'
    },
    {
      name: 'ROSEMARY CLARITY MATRIX',
      source: 'Salvia rosmarinus',
      class: 'AROMATIC BOTANICAL',
      evidence: 'LIMITED HUMAN',
      profile: 'herbal camphoraceous aromatic profile; alert and task-oriented sensory tone; 1,8-cineole-associated volatile architecture; low sedation',
      markers: ['alert', 'herbal', 'task focus', 'low sedation'],
      guardrail: 'Concentrated extracts require toxicology and route-specific review.'
    },
    {
      name: 'PEPPERMINT CLARITY MATRIX',
      source: 'Mentha × piperita',
      class: 'FOOD-GRADE BOTANICAL',
      evidence: 'SENSORY + LIMITED HUMAN',
      profile: 'cooling mint aromatic profile; crisp attention; low emotional weight; menthol and menthone-associated architecture; daytime context',
      markers: ['cooling', 'crisp', 'daytime', 'attention'],
      guardrail: 'Screen reflux, airway sensitivity and concentrated-oil toxicity.'
    },
    {
      name: 'CHAMOMILE CALM MATRIX',
      source: 'Matricaria chamomilla',
      class: 'FOOD-GRADE BOTANICAL',
      evidence: 'LIMITED HUMAN',
      profile: 'soft apple-floral profile; low-arousal calm; evening and decompression context; apigenin-containing botanical architecture; may increase sleepiness',
      markers: ['calm', 'soft', 'evening', 'sleepiness'],
      guardrail: 'Screen ragweed allergy, anticoagulants and additive sedation.'
    },
    {
      name: 'LEMON BALM MATRIX',
      source: 'Melissa officinalis',
      class: 'FOOD-GRADE BOTANICAL',
      evidence: 'LIMITED HUMAN',
      profile: 'gentle lemon-herbal profile; calm attention; low social friction; citral and rosmarinic-acid-containing architecture; moderate relaxation without a heavy sensory profile',
      markers: ['calm attention', 'lemon', 'social ease', 'moderate relaxation'],
      guardrail: 'Screen sedation, endocrine considerations and medication interactions.'
    },
    {
      name: 'GREEN TEA CLARITY CHASSIS',
      source: 'Camellia sinensis',
      class: 'BEVERAGE BOTANICAL',
      evidence: 'HUMAN EVIDENCE',
      profile: 'clean alertness; sustained attention; low body heaviness; caffeine and theanine-containing architecture; daytime functional context',
      markers: ['alert', 'clear', 'functional', 'daytime'],
      guardrail: 'Quantify stimulant load and screen cardiovascular, sleep and medication constraints.'
    },
    {
      name: 'CACAO SOCIAL CHASSIS',
      source: 'Theobroma cacao',
      class: 'FOOD-GRADE BOTANICAL',
      evidence: 'HUMAN + FOOD USE',
      profile: 'warm roasted sensory profile; gentle stimulation; social and rewarding context; theobromine-containing architecture; moderate duration',
      markers: ['warm', 'social', 'rewarding', 'gentle stimulation'],
      guardrail: 'Quantify methylxanthines and screen stimulant sensitivity and interactions.'
    },
    {
      name: 'GINGER BODY-BRIGHT MATRIX',
      source: 'Zingiber officinale',
      class: 'FOOD-GRADE BOTANICAL',
      evidence: 'HUMAN + FOOD USE',
      profile: 'warm spicy sensory profile; body brightness; low sedation; daytime or social context; gingerol and volatile-oil architecture',
      markers: ['warm body', 'bright', 'spicy', 'low sedation'],
      guardrail: 'Screen gastrointestinal tolerance, anticoagulants and pregnancy-specific constraints.'
    },
    {
      name: 'SAFFRON MOOD MATRIX',
      source: 'Crocus sativus',
      class: 'FOOD-GRADE BOTANICAL',
      evidence: 'HUMAN EVIDENCE · EMERGING',
      profile: 'warm floral sensory profile; positive mood and emotional color; low intoxication; crocin and safranal-containing architecture; requires standardized identity',
      markers: ['positive mood', 'warm', 'emotional color', 'low intoxication'],
      guardrail: 'Standardize identity and screen pregnancy, anticoagulants and serotonergic medications.'
    },
    {
      name: 'TULSI BALANCE MATRIX',
      source: 'Ocimum tenuiflorum',
      class: 'FOOD-GRADE BOTANICAL',
      evidence: 'LIMITED HUMAN',
      profile: 'green clove-like aromatic profile; balanced calm and alertness; low heaviness; eugenol and linalool-containing architecture; daytime decompression context',
      markers: ['balanced', 'calm alertness', 'green', 'daytime'],
      guardrail: 'Screen glucose, anticoagulant, fertility and medication considerations.'
    },
    {
      name: 'HEMP CBD CHASSIS',
      source: 'Cannabis sativa · compliant hemp',
      class: 'CANNABINOID CHASSIS',
      evidence: 'HUMAN EVIDENCE · CONTEXT DEPENDENT',
      profile: 'non-euphoric cannabinoid chassis; body calm and low stimulation; CBD-dominant architecture; interaction-heavy; product legality and analytical verification required',
      markers: ['non-euphoric', 'body calm', 'low stimulation', 'cannabinoid'],
      guardrail: 'Requires jurisdiction review, medication interaction screening and verified cannabinoid content.'
    },
    {
      name: 'HEMP CBG CHASSIS',
      source: 'Cannabis sativa · compliant hemp',
      class: 'CANNABINOID CHASSIS',
      evidence: 'EARLY HUMAN + PRECLINICAL',
      profile: 'low-intoxication cannabinoid chassis; clearer and less sedating target than CBD-dominant architecture; CBG-dominant profile; limited outcome evidence',
      markers: ['clear', 'low intoxication', 'low sedation', 'cannabinoid'],
      guardrail: 'Evidence remains early; require jurisdiction, toxicology and interaction review.'
    },
    {
      name: 'AROMATIC PLACEBO CONTROL',
      source: 'Matched sensory control',
      class: 'VALIDATION CONTROL',
      evidence: 'REQUIRED CONTROL',
      profile: 'matched aroma intensity and format without the target active architecture; used to separate expectancy, ritual and sensory effects from chemistry-specific outcomes',
      markers: ['control', 'blind testing', 'expectancy', 'sensory match'],
      guardrail: 'Must be designed by the study team to preserve blinding.'
    }
  ];

  function waitForField(timeout = 25000) {
    const started = performance.now();
    return new Promise((resolve, reject) => {
      const tick = () => {
        if (typeof state !== 'undefined' && state.products?.length && state.vectors?.length) {
          resolve();
          return;
        }
        if (performance.now() - started > timeout) {
          reject(new Error('CANA field or ARBITER query embed is not ready'));
          return;
        }
        setTimeout(tick, 150);
      };
      tick();
    });
  }

  function normalizeVector(values) {
    if (!Array.isArray(values) || values.length !== 72) throw new Error('ARBITER vector is not 72D');
    const vector = new Float32Array(values);
    let norm = 0;
    for (const value of vector) norm += value * value;
    norm = Math.sqrt(norm) || 1;
    for (let i = 0; i < vector.length; i += 1) vector[i] /= norm;
    return vector;
  }

  function vectorsFromResponse(data) {
    let rows = data?.vectors || data?.embeddings || data?.data;
    if (rows && !Array.isArray(rows) && typeof rows === 'object') {
      rows = rows.vectors || rows.embeddings || rows.data;
    }
    if (!Array.isArray(rows)) {
      if (Array.isArray(data?.embedding)) rows = [data.embedding];
      else if (Array.isArray(data?.vector)) rows = [data.vector];
    }
    if (!Array.isArray(rows)) throw new Error('ARBITER returned no vectors');
    return rows.map((row) => {
      const values = Array.isArray(row) ? row : row?.embedding || row?.vector;
      return normalizeVector(values);
    });
  }

  async function embedMany(texts) {
    let lastError = null;
    const endpoints = [...new Set([
      '/api/embed',
      ...(Array.isArray(state.embedUrls) ? state.embedUrls : []),
      'https://cana-embed.actualgeneralintelligence.com/v1/embed'
    ].filter(Boolean))];
    for (const url of endpoints) {
      try {
        const response = await fetch(url, {
          method: 'POST',
          mode: url.startsWith('/') ? 'same-origin' : 'cors',
          cache: 'no-store',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ texts, use_freq: state.useFreq !== false })
        });
        if (!response.ok) throw new Error(`${response.status} from ${url}`);
        const vectors = vectorsFromResponse(await response.json());
        if (vectors.length !== texts.length) throw new Error(`Expected ${texts.length} vectors; received ${vectors.length}`);
        return vectors;
      } catch (error) {
        lastError = error;
      }
    }
    throw lastError || new Error('No ARBITER endpoint is configured');
  }

  function dot(a, b) {
    let score = 0;
    for (let i = 0; i < 72; i += 1) score += a[i] * b[i];
    return score;
  }

  function rankExisting(targetVector, limit = 8) {
    const ranked = [];
    const vectors = state.vectors;
    for (let index = 0; index < state.products.length; index += 1) {
      const base = index * 72;
      let score = 0;
      for (let axis = 0; axis < 72; axis += 1) score += vectors[base + axis] * targetVector[axis];
      ranked.push({ index, row: state.products[index], score });
    }
    ranked.sort((a, b) => b.score - a.score || a.index - b.index);
    return ranked.slice(0, limit);
  }

  function formData() {
    const selectedGuardrails = qa('input[name="guardrail"]:checked', form).map((input) => input.value);
    return {
      intent: intent.value.trim(),
      path: q('#designPath').value,
      thc: q('#designThc').value,
      duration: q('#designDuration').value,
      route: q('#designRoute').value,
      guardrails: selectedGuardrails
    };
  }

  function canonicalTarget(spec) {
    const pathText = {
      both: 'Find both a real cannabis cultivar development path and a natural-product analogue.',
      cultivar: 'Develop a real cannabis cultivar and identify phenotype benchmarks and candidate parents.',
      botanical: 'Develop a standardized natural-product effect architecture without presenting a consumer recipe.'
    }[spec.path];
    return [
      `Desired human state: ${spec.intent}.`,
      pathText,
      `THC architecture: ${spec.thc}.`,
      `Desired duration: ${spec.duration}.`,
      `Preferred route or format: ${spec.route}.`,
      spec.guardrails.length ? `Hard guardrails: avoid ${spec.guardrails.join(', ')}.` : 'Hard guardrails: preserve consistency and low adverse-effect variance.',
      'Prioritize reproducible chemistry, blind outcome measurement, analytical batch verification, functional clarity, and lawful research development.'
    ].join(' ');
  }

  function scoreLabel(score) {
    return Number.isFinite(score) ? score.toFixed(3) : '—';
  }

  function productMeta(row) {
    return [row.brand || row.vendor, row.category || row.type || row.format, row.subcategory || row.subtype || row.product_type]
      .filter(Boolean).join(' · ') || 'FIELD RECORD';
  }

  function renderExisting(items) {
    if (!items.length) return '<div class="design-result"><div class="design-result-score">—</div><div><h3>No field benchmark</h3><p>The current field returned no measurable record.</p></div></div>';
    return items.map(({ row, score }) => `
      <article class="design-result">
        <div class="design-result-score">${scoreLabel(score)}</div>
        <div><h3>${esc(row.name || row.title || 'Untitled record')}</h3><p>${esc(productMeta(row))}</p></div>
        <em>PHENOTYPE BENCHMARK</em>
      </article>`).join('');
  }

  function renderNatural(items) {
    return items.map(({ item, score }) => `
      <article class="design-result">
        <div class="design-result-score">${scoreLabel(score)}</div>
        <div><h3>${esc(item.name)}</h3><p>${esc(item.source)} · ${esc(item.markers.join(' · '))}</p></div>
        <em>${esc(item.evidence)}</em>
      </article>`).join('');
  }

  function signatureRows(spec) {
    const rows = [
      ['DEVELOPMENT PATH', spec.path === 'both' ? 'CULTIVAR + BOTANICAL' : spec.path.toUpperCase()],
      ['THC ARCHITECTURE', spec.thc.toUpperCase()],
      ['DURATION', spec.duration.toUpperCase()],
      ['FORMAT', spec.route.toUpperCase()],
      ['GUARDRAILS', spec.guardrails.length ? spec.guardrails.join(' · ').toUpperCase() : 'CONSISTENCY · LOW VARIANCE']
    ];
    return rows.map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('');
  }

  function programSteps(spec, benchmarks, natural) {
    const benchmarkNames = benchmarks.slice(0, 2).map(({ row }) => row.name || row.title).filter(Boolean).join(' + ') || 'top measured field benchmarks';
    const naturalNames = natural.slice(0, 3).map(({ item }) => item.name.replace(' MATRIX', '').replace(' CHASSIS', '')).join(' + ');
    const first = spec.path === 'botanical'
      ? `Lock the target state and the adverse-effect exclusions before selecting materials.`
      : `Use ${benchmarkNames} as phenotype references. Confirm that any proposed parent record has traceable genetics before breeding.`;
    const second = spec.path === 'cultivar'
      ? 'Translate the target into a cannabinoid, volatile and functional-performance assay panel. Do not select on THC alone.'
      : `Begin with ${naturalNames} as measured candidate classes, not a finished recipe. Verify identity, purity, legality and route suitability.`;
    const third = spec.path === 'botanical'
      ? 'Create analytically distinct prototypes under qualified product-development controls; exclude combinations with unresolved interactions.'
      : 'Generate segregating populations, measure chemistry and phenotype each candidate, then retain only plants that reproduce the target state across batches.';
    const fourth = 'Run randomized, blinded outcome collection with an aromatic or format-matched control. Capture onset, duration, clarity, anxiety, body load, appetite and next-day effect.';
    const fifth = 'Feed measured chemistry and outcome vectors back into ARBITER. Advance only designs whose chemistry, experience and safety signals converge reproducibly.';
    return [first, second, third, fourth, fifth];
  }

  function renderProgram(steps) {
    const titles = ['DEFINE', 'ARCHITECT', 'BUILD', 'BLIND', 'SELECT'];
    return steps.map((text, index) => `
      <article class="design-step"><b>${String(index + 1).padStart(2, '0')}</b><h3>${titles[index]}</h3><p>${esc(text)}</p></article>
    `).join('');
  }

  async function runDesign(event) {
    event?.preventDefault();
    const spec = formData();
    if (!spec.intent) {
      intent.focus();
      status.innerHTML = '<span>DESCRIBE THE STATE FIRST</span><strong>INPUT REQUIRED</strong>';
      return;
    }

    submit.disabled = true;
    output.hidden = true;
    status.innerHTML = '<span>MEASURING TARGET + CANDIDATE ARCHITECTURES</span><strong>ARBITER / 72D</strong>';
    const started = performance.now();

    try {
      await waitForField();
      const targetText = canonicalTarget(spec);
      const naturalTexts = NATURAL_LIBRARY.map((item) => `${item.profile}. Evidence posture: ${item.evidence}. Guardrail: ${item.guardrail}`);
      const [targetVector, ...naturalVectors] = await embedMany([targetText, ...naturalTexts]);
      const benchmarks = rankExisting(targetVector, 8);
      const natural = NATURAL_LIBRARY.map((item, index) => ({ item, score: dot(targetVector, naturalVectors[index]) }))
        .sort((a, b) => b.score - a.score)
        .slice(0, 7);
      const elapsed = performance.now() - started;
      const steps = programSteps(spec, benchmarks, natural);

      q('#designTargetText').textContent = spec.intent;
      q('#designSignature').innerHTML = signatureRows(spec);
      q('#designBenchmarks').innerHTML = renderExisting(benchmarks);
      q('#designNatural').innerHTML = renderNatural(natural);
      q('#designProgram').innerHTML = renderProgram(steps);
      q('#designNaturalPanel').hidden = spec.path === 'cultivar';
      q('#designBenchmarkPanel').hidden = spec.path === 'botanical';
      q('#designProgramLabel').textContent = spec.path === 'both' ? 'DUAL DEVELOPMENT PROGRAM' : `${spec.path.toUpperCase()} DEVELOPMENT PROGRAM`;
      q('#designElapsed').textContent = `${Math.round(elapsed)} MS · ${state.products.length.toLocaleString()} FIELD RECORDS + ${NATURAL_LIBRARY.length} MATERIAL CLASSES`;

      latestSpec = {
        schema: 'cana-effect-design-v1',
        created_at: new Date().toISOString(),
        target: spec,
        target_text: targetText,
        measured_by: 'ARBITER 72D',
        existing_benchmarks: benchmarks.map(({ row, score }) => ({
          name: row.name || row.title,
          category: row.category || row.type || row.format,
          score
        })),
        natural_candidates: natural.map(({ item, score }) => ({
          name: item.name,
          source: item.source,
          class: item.class,
          evidence: item.evidence,
          score,
          guardrail: item.guardrail
        })),
        development_program: steps,
        safety_boundary: 'Research and product-development specification only. No consumer dosing or mixing instructions.'
      };

      output.hidden = false;
      status.innerHTML = `<span>DESIGN FIELD MEASURED</span><strong>${Math.round(elapsed)} MS · ARBITER 72D</strong>`;
      output.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      console.error(error);
      status.innerHTML = `<span>${esc(error.message)}</span><strong>MEASUREMENT FAILED</strong>`;
    } finally {
      submit.disabled = false;
    }
  }

  function setMode(mode) {
    const design = mode === 'design';
    document.body.classList.toggle('cana-design-mode', design);
    lab.hidden = !design;
    qa('[data-cana-mode]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.canaMode === mode)));
    history.replaceState(null, '', design ? '#design' : '#top');
    if (design) intent.focus();
    else if (typeof input !== 'undefined') input.focus();
  }

  function exportSpec() {
    if (!latestSpec) return;
    const blob = new Blob([JSON.stringify(latestSpec, null, 2) + '\n'], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `cana-effect-design-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  qa('[data-cana-mode]').forEach((button) => button.addEventListener('click', () => setMode(button.dataset.canaMode)));
  qa('[data-design-example]').forEach((button) => button.addEventListener('click', () => {
    intent.value = button.dataset.designExample || '';
    intent.focus();
  }));
  form.addEventListener('submit', runDesign);
  exportButton.addEventListener('click', exportSpec);

  if (location.hash === '#design') setMode('design');
})();
