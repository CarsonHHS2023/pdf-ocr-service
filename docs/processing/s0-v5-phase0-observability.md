# S0 v5 Phase 0 observability and shadow-planner contract

## Goal

Phase 0 measures the current Staging S0 path before S0 v5 is allowed to change
processing behavior. It adds operation-level timing/count telemetry and runs a
conservative treatment planner in shadow mode against the same pages processed
by current v4.

Phase 0 is **not** a performance optimization and is **not** an output cutover.
Current v4 remains authoritative for PDF bytes, page routes, geometry/background
acceptance, presentation decisions, provider input, and OCR behavior.

## Staging-only installation

The installer is:

```text
scripts/apply_s0_v5_phase0_observability.py
```

It is invoked only by:

- Staging Backend Integration CI; and
- the `staging` branch Hugging Face deployment workflow.

The installer runs after the existing production-equivalent overlay chain. It
therefore observes the actual composed Staging path instead of a simplified
standalone copy of v4. Production deployment workflows do not install it.

## Non-interference invariants

The Phase 0 compatibility layer must preserve all of these invariants:

1. `_combined_features()` returns the exact delegate feature object. Shadow-only
   fields are never injected into presentation-classifier input.
2. The top-level preprocessing wrapper returns the exact delegate result object.
3. Shadow planning never selects pixels or changes a v4 gate.
4. A shadow observation/finalization/logging failure fails open and current v4
   continues normally.
5. An exception from the authoritative delegate is re-raised unchanged.
6. No provider, storage, OCR, page-count, page-order, or quality threshold is
   changed in Phase 0.

The tests in `tests/test_s0_v5_phase0_observability.py` enforce these properties.

## Timed stages

The final `PDF_S0_PROFILE` summary aggregates milliseconds and invocation counts
for the composed Staging path, including:

- `inspect_structure_ms`;
- `render_120_ms`;
- `render_300_ms`;
- `render_150_diagnostics_ms`;
- `color_analysis_ms`;
- `geometry_build_ms`;
- `geometry_gate_ms`;
- `background_build_ms`;
- `background_gate_ms`;
- `output_insert_ms`;
- `ordinary_source_build_ms`;
- `chunk_serialize_ms`;
- `chunk_merge_ms`;
- `presentation_render_assembly_ms`.

The top-level wrapper also reports `total_s0_ms`. Shadow-observation and shadow
finalization time are reported separately so planner overhead is visible instead
of being confused with the legacy treatment cost.

## Shadow observations

The planner observes the existing 120-DPI analysis raster plus native PDF page
structure. Per-page observations include:

- born-digital signal;
- embedded-image count and maximum image coverage;
- whether the page is a single full-page raster;
- native raster width/height and effective DPI;
- near-white and border-connected-white ratios;
- low-frequency background standard deviation/range;
- dark-pixel and saturation signals;
- cheap skew confidence/angle;
- cheap perspective coverage/distortion.

The planner does not request another 300-DPI render to make these observations.

## Document profile

After the authoritative delegate finishes, Phase 0 builds a shadow document
profile. Initial profile labels are:

- `born_digital`;
- `uniform_clean_scan`;
- `uniform_gray_scan`;
- `photographic_or_color_mixed`;
- `mixed_document`.

The profile also records whether full-page native raster DPI is consistent across
the observed document. This is the eligibility signal for later Native
Full-Page Raster experiments; it does not activate a fast path in Phase 0.

## Shadow treatment routes

The shadow planner predicts one of:

- `passthrough`;
- `geometry_only`;
- `background_only`;
- `geometry_and_background`;
- `high_res_confirm`.

The planner is intentionally conservative. An uncertain cheap observation is
escalated instead of being declared safe passthrough.

## Comparison against current v4

Once current v4 has produced its manifest, Phase 0 compares each ordinary page's
shadow route with actual accepted v4 components. Presentation pages are excluded
from this v4 component comparison because their authoritative route is different.

The summary records:

- `false_negative_passthrough_count`: shadow said passthrough, while current v4
  actually accepted geometry and/or background treatment;
- `route_miss_count`: the shadow route lacked a treatment component that current
  v4 accepted;
- `unnecessary_escalation_count`: shadow requested expensive confirmation or
  treatment while current v4 ultimately changed nothing.

For shadow rollout, false-negative passthrough and route misses are the critical
safety metrics. Unnecessary escalation is primarily an efficiency metric.

## Telemetry output

Structured profile logs use the prefix:

```text
PDF_S0_PROFILE
```

Key events are:

- `s0_phase0_installed`;
- `s0_phase0_started`;
- `legacy_page_complete`;
- `shadow_page_observation_failed` when a shadow-only page observation fails;
- `s0_phase0_delegate_failed` when the authoritative path itself fails;
- `s0_phase0_summary` on successful completion.

One bounded scalar checkpoint is also persisted through the existing S0 resource
heartbeat with phase `s0_v5_shadow_summary`. It includes total S0 time, 120/300
render counts, false-negative count, route-miss count, and unnecessary-escalation
count. `ProcessingRun` remains observability/provenance state, not queue truth.

## Benchmark procedure

Use the locked benchmark identity in `s0-v5-bounded-benchmark.md`.

For the 100-page benchmark:

1. run current Staging S0 with Phase 0 installed;
2. retain the final `s0_phase0_summary` and resource heartbeat;
3. record wall time, stage times/counts, changed page count, peak RSS, planner
   profile, shadow route counts, and comparison counts;
4. do not require a full 528-page legacy completion before proceeding;
5. once the shadow planner has acceptable recall on the bounded corpus, run the
   full 528-page source as an observability/acceptance exercise.

## Exit criteria for selective-treatment Phase 1

Phase 1 may make planner decisions authoritative only after the bounded corpus
shows:

- zero unexplained output-contract regressions;
- no shadow failures affecting current v4 execution;
- false-negative passthrough rate compatible with the >=99% heavy-page recall
  target, with known misses converted into conservative planner rules;
- stage telemetry clearly identifying the dominant current costs;
- Native Full-Page Raster candidates explicitly quantified rather than assumed;
- quality review confirms that any proposed work elimination does not weaken
  gray-background cleanup, geometry correction, dark-foreground retention,
  edge/line retention, color protection, presentation routing, or orientation.
