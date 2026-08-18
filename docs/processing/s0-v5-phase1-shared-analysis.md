# S0 v5 Phase 1 — Shared Analysis and Single Heavy Work

Status: Staging implementation / runtime validation required  
Product milestone: horizontal-only  
Scalability phase: S0  
Production effect: none

## Purpose

Phase 0 established that the current high-quality S0 path is correct but performs the expensive raster/geometry analysis twice: first for presentation-page classification and again for ordinary OpenCV v4 treatment.

Phase 1 removes that duplicated heavy computation without changing presentation classification policy or OpenCV quality gates.

The design target is:

```text
source page
  -> one shared low-resolution analysis
  -> existing authoritative classification chain
  -> at most one 300-DPI source/geometry computation
  -> ordinary or presentation treatment reuses equivalent evidence
```

The implementation remains page-bounded in memory and uses only run-local temporary scratch for large reusable rasters.

## Locked Phase 0 benchmark

The comparison fixture is:

```text
s0_benchmark_100pages_seeded_with_page302.pdf
```

Source size: `12,486,675` bytes.

Phase 0 evidence:

| Metric | Phase 0 |
| --- | ---: |
| Pages | 100 |
| Total S0 time | 1,552,777.406 ms (~25m52.8s) |
| Peak RSS | 753.2 MiB |
| 120-DPI renders | 200 |
| 300-DPI renders | 200 |
| Changed pages | 99 |
| Provider input size | 87,179,148 bytes |
| Shadow false-negative passthrough | 0 |
| Shadow route miss | 0 |
| Shadow unnecessary escalation | 0 |

The dirty-page distribution was approximately:

- geometry + background: 69 pages;
- background only: 25 pages;
- geometry only: 5 pages;
- original: 1 page.

This distribution is expected for the benchmark and must not be optimized away by forcing pages toward passthrough.

## Root cause addressed

The Phase 0 path performs two heavy phases.

### Presentation classification phase

For each page it may perform:

1. 120-DPI analysis render;
2. native/presentation/orientation features;
3. candidate selection;
4. high-resolution orientation confirmation when required;
5. 300-DPI geometry source render for candidates;
6. geometry candidate + quality gate;
7. multimodal presentation classification and existing conflict/fail-open checks.

### Ordinary v4 phase

Ordinary pages are then serialized into a provider subset PDF and processed again:

1. page structure inspection;
2. 120-DPI analysis render;
3. color analysis;
4. 300-DPI source render;
5. geometry candidate + quality gate;
6. background normalization + quality gate;
7. raster/original output selection.

Presentation render assembly can also request geometry again for presentation pages.

Phase 1 removes equivalent duplicate render/geometry work while retaining the same decision functions and the same composed classifier chain.

## Composition boundary

### The classifier pipeline is authoritative and untouched

Phase 1 does **not** replace or copy `presentation._classify_source_pages`.

This is a hard architecture boundary because the already-composed classifier includes behavior from multiple compatibility layers, including:

- discrete orientation detection/correction;
- high-resolution confirmation;
- native-PDF text acceptance and raster fallback;
- analysis/geometry fail-open handling;
- presentation/native page decisions;
- bounded-memory decision cleanup.

Phase 1 sits below this chain. It wraps low-level operations that the chain already calls and returns the exact authoritative results on first computation.

A regression test statically rejects any Phase 1 installer assignment to `_classify_source_pages`.

### Phase 0 accounting is inside the Phase 1 cache layer

Staging installation order is intentionally:

```text
existing production-equivalent overlays
  -> bounded-v4 compatibility
  -> cheap shadow geometry
  -> S0 v5 Phase 0 observability
  -> S0 v5 Phase 1 low-level cache
  -> bound pdf_ingestion imports
```

Phase 1 therefore captures Phase-0-wrapped expensive delegates. A real cache miss calls the Phase 0 delegate and is timed/counted normally. A cache hit skips that delegate, so Phase 0 counters represent actual expensive work rather than logical page visits.

## Phase 1 architecture

### Run-local shared scope

Each S0 execution owns an isolated `ContextVar` state containing only that run's lightweight evidence, provider-page mapping, transient current-page rasters, and temporary scratch references.

No shared global page cache is used between documents or users.

The run scope is reset on both successful and failed processing.

### One low-resolution analysis image

Phase 1 wraps the existing authoritative `bridge._analysis_image` function.

The first call for a page still executes that function exactly as before. The returned image is then retained only for the current source page. The same image can satisfy later same-page 120-DPI renderer requests without a second rasterization.

Phase 1 also derives optimization-only V4 evidence from that image:

- color features;
- source-page structure evidence.

Failures while producing this optimization evidence are fail-open: the authoritative classification image is still returned unchanged and later V4 work is recomputed normally.

The low-resolution image is replaced when analysis advances to the next page, so it does not accumulate across the document.

### Same-page 300-DPI render reuse

Phase 1 wraps the existing Phase-0-profiled V4 renderer.

For the current source page, the first 300-DPI request performs the normal render. Later same-page 300-DPI requests reuse that exact raster in memory. This covers cases such as high-resolution orientation confirmation followed by geometry analysis without retaining a whole-document 300-DPI array set.

The transient current-page 300-DPI raster is released before the ordinary provider-document phase.

### Authoritative base and oriented geometry reuse

Phase 1 wraps both existing geometry entry points:

- `bridge._geometry_only_page`;
- `orientation._oriented_geometry`.

It also wraps the existing V4 geometry gate only to capture its exact return tuple. The gate implementation and thresholds are not replaced.

For oriented pages, Phase 1 keeps two concepts separate:

- the presentation-level geometry decision, which can be accepted because a discrete orientation correction was applied;
- the underlying V4 geometry-gate acceptance, which determines whether ordinary V4 should treat perspective/deskew geometry as accepted.

This avoids turning a pure 90/180/270-degree orientation correction into a false V4 geometry acceptance.

### Provider-page equivalence rules

The ordinary provider builder remains authoritative and its `provider_input_mode` is captured for each provider page.

Reuse is deliberately restricted:

- `pdf_page`: original structure, color, and geometry evidence may be reused;
- `orientation_corrected_raster`: color distribution and oriented geometry may be reused, but page structure is re-inspected because rasterization changes born-digital semantics;
- native-text fallback raster modes: original geometry is not reused; authoritative V4 analysis is recomputed.

Chunk-local provider indexes are translated back to original source page numbers through the existing provider map plus the bounded-v4 chunk offset.

### Temporary scratch boundary

Large geometry-selected/orientation rasters are not retained in the whole-document Python object graph. They are written losslessly as local `.npy` scratch files under a temporary run directory.

The scratch directory:

- is process/run local;
- is deleted when the top-level S0 call completes or fails;
- is never uploaded to object storage;
- is never exposed through a source reference;
- is not a durable artifact or business record.

Phase 1 emits bounded counters for scratch read/write file counts and bytes. The benchmark must verify that scratch I/O does not become the next dominant cost. If it does, the next optimization should preserve pixel identity while reducing scratch traffic rather than reintroducing duplicate rendering.

### Existing bounded-v4 chunking remains

The 16-page ordinary-v4 chunk coordinator remains the memory boundary.

Phase 1 replaces only its base page processor with a shared-aware processor. If provider mapping, cache evidence, or scratch is unavailable/inapplicable, that page falls back to the existing OpenCV v4 render/build/gate functions.

## Quality invariants

Phase 1 must not change:

- presentation page-role vocabulary;
- presentation model/provider behavior;
- presentation confidence threshold;
- high-resolution presentation confirmation;
- continuous-body-prose conflict protection;
- native-PDF text acceptance/fallback behavior;
- discrete orientation handling or confirmation;
- OpenCV geometry candidate algorithm;
- geometry quality gate;
- background normalization algorithm;
- background quality gate;
- dark foreground protection;
- color-critical background protection;
- born-digital preservation;
- clean/original fallback semantics;
- provider page-map semantics;
- Modal/provider sharding policy.

A cache or scratch failure is an optimization failure, not a document-processing failure: the authoritative current work must be recomputed.

## Runtime acceptance gate

CI passing is necessary but is not sufficient to validate Phase 1.

After the candidate is merged only to `staging` and deployed by the staging-branch workflow, rerun the exact locked 100-page benchmark and compare with Phase 0.

Required evidence:

1. `render_120_count` moves from `200` toward `100`.
2. `render_300_count` moves from `200` toward `100` for this raster-heavy fixture.
3. Geometry build/gate calls are no longer duplicated for equivalent source/provider pages.
4. `changed_page_count` remains consistent with the Phase 0 result (`99`) unless a concrete page-level quality review explains a difference.
5. Presentation/native/orientation classification behavior remains equivalent on known presentation/mixed pages.
6. `shadow_false_negative_count == 0`.
7. `shadow_route_miss_count == 0`.
8. No new unnecessary escalation regression is introduced.
9. Peak RSS remains bounded; it must not scale with accumulated 300-DPI page arrays.
10. Provider input/page mapping remains valid.
11. Scratch is cleaned after terminal success/failure.
12. Total S0 wall time materially improves versus the 1,552,777.406 ms Phase 0 baseline.

A successful benchmark should also record Phase 1 cache metrics from:

```text
PDF_S0_V5_PHASE1_SHARED_ANALYSIS_COMPLETE
```

including:

- analysis page/evidence counts;
- 120-DPI and same-page 300-DPI cache hits;
- ordinary structure/color/geometry cache hits;
- presentation geometry/orientation-source reuse;
- scratch read/write file counts and bytes.

## Staging validation sequence

1. CI and code review pass on the exact PR head.
2. Merge only to `staging`.
3. Let the staging-branch workflow deploy the exact staging head to the HF Staging Space.
4. Run the locked 100-page benchmark.
5. If runtime evidence regresses, revert only Staging.
6. Do not promote Phase 1 to `main` / Production until runtime evidence satisfies the gate.

## Non-goals

Phase 1 does not yet:

- move S0 CPU work to Modal;
- add local multiprocessing;
- introduce cross-document or cross-user cache reuse;
- change object-storage architecture;
- change provider timeout or source-grant TTL;
- redesign presentation classification;
- change OCR/Modal concurrency or batch size.

After Phase 1 is validated, the next execution step is a book-scoped CPU worker with bounded local multiprocessing, using the shared page-analysis/treatment boundary established here.
