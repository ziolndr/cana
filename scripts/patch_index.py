#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "CANA_DESIGN_V1"

MODE_NAV = '''<!-- CANA_DESIGN_V1:MODE_NAV -->
    <nav class="cana-mode-nav" aria-label="CANA mode">
      <button type="button" data-cana-mode="find" aria-pressed="true">FIND</button>
      <button type="button" data-cana-mode="design" aria-pressed="false">DESIGN</button>
    </nav>
    <!-- /CANA_DESIGN_V1:MODE_NAV -->'''

DESIGN_LAB = '''<!-- CANA_DESIGN_V1:LAB -->
    <section class="design-lab" id="designLab" aria-label="CANA effect design" hidden>
      <div class="design-intro">
        <div>
          <span class="design-kicker">ARBITER / EFFECT DESIGN FIELD</span>
          <h1>Design the state.<br>Find the chemistry.</h1>
          <p>Measure a desired human state against the existing CANA field and a controlled library of natural-product architectures. Produce a real cultivar development path, a botanical analogue, or both.</p>
        </div>
        <aside class="design-principle">
          <span>THE DESIGN UNIT</span>
          <strong>State × chemistry × format × context × verified outcome.</strong>
        </aside>
      </div>

      <form class="design-form-shell" id="designForm" autocomplete="off">
        <div class="design-form">
          <label class="design-field" for="designIntent">
            <span>DESCRIBE THE EXACT STATE</span>
            <textarea id="designIntent" spellcheck="false" placeholder="warm social confidence, vivid music, clear speech, no racing thoughts, two-hour window"></textarea>
          </label>
          <label class="design-field" for="designPath">
            <span>DEVELOPMENT PATH</span>
            <select id="designPath">
              <option value="both">CULTIVAR + BOTANICAL</option>
              <option value="cultivar">REAL CULTIVAR</option>
              <option value="botanical">NATURAL-PRODUCT ANALOGUE</option>
            </select>
          </label>
          <label class="design-field" for="designThc">
            <span>THC ARCHITECTURE</span>
            <select id="designThc">
              <option value="unconstrained but measured">MEASURED / UNCONSTRAINED</option>
              <option value="zero THC">ZERO THC</option>
              <option value="trace THC">TRACE THC</option>
              <option value="low THC with preserved function">LOW THC / FUNCTIONAL</option>
              <option value="balanced THC and CBD">BALANCED THC / CBD</option>
            </select>
          </label>
        </div>

        <div class="design-form">
          <label class="design-field" for="designDuration">
            <span>DESIRED WINDOW</span>
            <select id="designDuration">
              <option value="60 to 120 minutes">60–120 MINUTES</option>
              <option value="under 60 minutes">UNDER 60 MINUTES</option>
              <option value="2 to 4 hours">2–4 HOURS</option>
              <option value="overnight">OVERNIGHT</option>
            </select>
          </label>
          <label class="design-field" for="designRoute">
            <span>FORMAT / ROUTE</span>
            <select id="designRoute">
              <option value="format agnostic; select by onset and safety">FORMAT AGNOSTIC</option>
              <option value="inhaled flower or vapor with rapid onset">FLOWER / VAPOR</option>
              <option value="oral beverage or food format">BEVERAGE / FOOD</option>
              <option value="sublingual standardized extract">SUBLINGUAL</option>
              <option value="aromatic non-ingested format">AROMATIC / NON-INGESTED</option>
            </select>
          </label>
          <div class="design-field">
            <span class="design-guardrail-title">HARD EXCLUSIONS</span>
            <div class="design-guardrails">
              <label class="design-check"><input type="checkbox" name="guardrail" value="anxiety or racing thoughts">ANXIETY</label>
              <label class="design-check"><input type="checkbox" name="guardrail" value="sleepiness or heavy sedation">SEDATION</label>
              <label class="design-check"><input type="checkbox" name="guardrail" value="appetite increase">APPETITE</label>
              <label class="design-check"><input type="checkbox" name="guardrail" value="verbal or working-memory impairment">IMPAIRMENT</label>
            </div>
          </div>
        </div>

        <div class="design-actions">
          <div class="design-examples" aria-label="Effect design examples">
            <button type="button" data-design-example="social warmth and musical immersion with clear speech and no anxiety">SOCIAL / MUSIC</button>
            <button type="button" data-design-example="calm body, preserved working memory, low appetite and no sleepiness">CALM / FUNCTIONAL</button>
            <button type="button" data-design-example="bright creative attention, tactile vividness and a clean two-hour finish">CREATIVE / CLEAN</button>
          </div>
          <button class="design-submit" id="designSubmit" type="submit">MEASURE DESIGN</button>
        </div>
      </form>

      <div class="design-status" id="designStatus"><span>READY TO DEFINE A STATE</span><strong>ARBITER / 72D</strong></div>

      <section class="design-output" id="designOutput" hidden>
        <div class="design-grid">
          <article class="design-panel design-panel--target">
            <div>
              <div class="design-panel-head"><span>01 / TARGET STATE</span><strong>MEASURED SPECIFICATION</strong></div>
              <h2 class="design-target-text" id="designTargetText"></h2>
            </div>
            <div class="design-signature" id="designSignature"></div>
          </article>

          <article class="design-panel design-panel--benchmarks" id="designBenchmarkPanel">
            <div class="design-panel-head"><span>02 / EXISTING FIELD</span><strong>PHENOTYPE BENCHMARKS</strong></div>
            <div class="design-list" id="designBenchmarks"></div>
          </article>

          <article class="design-panel design-panel--natural" id="designNaturalPanel">
            <div class="design-panel-head"><span>03 / NATURAL ARCHITECTURE</span><strong>MEASURED CANDIDATES</strong></div>
            <div class="design-list" id="designNatural"></div>
          </article>

          <article class="design-panel design-panel--program">
            <div class="design-panel-head"><span>04 / DEVELOPMENT</span><strong id="designProgramLabel">DUAL DEVELOPMENT PROGRAM</strong></div>
            <div class="design-program" id="designProgram"></div>
          </article>
        </div>
        <div class="design-foot">
          <span id="designElapsed">—</span>
          <span>RESEARCH + PRODUCT-DEVELOPMENT SPECIFICATION · NO CONSUMER DOSING OR MIXING INSTRUCTIONS</span>
          <button class="design-export" id="designExport" type="button">EXPORT SPEC</button>
        </div>
      </section>
    </section>
    <!-- /CANA_DESIGN_V1:LAB -->'''


def strip_existing(text: str) -> str:
    text = re.sub(
        r'(?ms)^[ \t]*<!-- CANA_DESIGN_V1:MODE_NAV -->.*?^[ \t]*<!-- /CANA_DESIGN_V1:MODE_NAV -->[ \t]*\n?',
        '',
        text,
    )
    text = re.sub(
        r'(?ms)^[ \t]*<!-- CANA_DESIGN_V1:LAB -->.*?^[ \t]*<!-- /CANA_DESIGN_V1:LAB -->[ \t]*\n?',
        '',
        text,
    )
    text = re.sub(r'(?mi)^[ \t]*<link[^>]+cana-design\.css[^>]*>[ \t]*\n?', '', text)
    text = re.sub(r'(?mi)^[ \t]*<script[^>]+cana-design\.js[^>]*></script>[ \t]*\n?', '', text)
    return text


def patch(path: Path) -> None:
    text = strip_existing(path.read_text(encoding="utf-8"))
    text = re.sub(r'<title>.*?</title>', '<title>CANA — Effect Design Field</title>', text, count=1, flags=re.S | re.I)
    text = re.sub(
        r'<meta\s+name=["\']description["\']\s+content=["\'].*?["\']\s*/?>',
        '<meta name="description" content="Search existing cannabis profiles and design reproducible cultivar or natural-product effect architectures through ARBITER 72D geometry.">',
        text,
        count=1,
        flags=re.S | re.I,
    )
    if '</head>' not in text:
        raise SystemExit(f"No </head> in {path}")
    text = text.replace('</head>', '  <link rel="stylesheet" href="assets/cana-design.css?v=effect-design-1">\n</head>', 1)

    connection = re.search(r'(?m)^\s*<div class="system-status" id="connection">', text)
    if not connection:
        raise SystemExit(f"No CANA connection marker in {path}")
    text = text[:connection.start()] + MODE_NAV + '\n' + text[connection.start():]

    field = re.search(r'(?m)^\s*<section class="field-shell"', text)
    if not field:
        raise SystemExit(f"No field-shell in {path}")
    text = text[:field.start()] + DESIGN_LAB + '\n' + text[field.start():]

    app_script = list(re.finditer(r'<script[^>]+src=["\'][^"\']*assets/app\.js[^"\']*["\'][^>]*></script>', text, flags=re.I))
    if not app_script:
        raise SystemExit(f"No assets/app.js script in {path}")
    insert_at = app_script[-1].end()
    text = text[:insert_at] + '\n      <script src="assets/cana-design.js?v=effect-design-1"></script>' + text[insert_at:]

    if MARKER not in text:
        raise SystemExit("Patch marker was not written")
    path.write_text(text, encoding="utf-8")
    print(f"PATCHED · {path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: patch_index.py index.html [web/index.html ...]")
    for argument in sys.argv[1:]:
        path = Path(argument)
        if path.is_file():
            patch(path)
