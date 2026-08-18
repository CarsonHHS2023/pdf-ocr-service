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
  -> presentation classification evidence
  -> at most one 300-DPI source/geometry computation
  -> ordinary or presentation treatment reuses that evidence
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
2. local/native presentation features;
3. candidate selection;
4. 300-DPI geometry source render for candidates;
5. geometry candidate + quality gate;
6. multimodal presentation classification.

### Ordinary v4 phase

Ordinary pages are then serialized into a subset PDF and processed again:

1. page structure inspection;
2. 120-DPI analysis render;
3. color analysis;
4. 300-DPI source render;
5. geometry candidate + quality gate;
6. background normalization + quality gate;
7. raster/original output selection.

Presentation render assembly can also request geometry again for presentation pages.

Phase 1 removes the duplicate render/geometry work while retaining the same decision functions.

## Phase 1 architecture

### Run-local shared scope

Each S0 execution owns an isolated `ContextVar` state containing only that run's evidence and provider-page mapping.

No shared global page cache is used between documents or users.

The run scope is reset on both successful and failed processing.

### One low-resolution analysis image

The classify-first pass renders one 120-DPI image for each source page. The same image feeds:

- existing presentation image features;
- OpenCV v4 color evidence;
- the presentation classifier when geometry is not selected.

V4 page-structure evidence is also recorded during this pass.

The classification model, feature extraction functions, candidate rules, confidence thresholds, high-resolution confirmation layer, continuous-prose conflict gate, and fallback behavior are not replaced.

### Authoritative geometry reuse

Phase 1 wraps the already-installed `bridge._geometry_only_page` delegate. It does not replace that delegate's geometry thresholds or quality checks.

When the delegate runs, Phase 1 captures the source 300-DPI render and retains the final geometry-selected raster. The returned geometry decision remains authoritative.

For later ordinary-page treatment:

- accepted geometry reuses the accepted geometry raster;
- rejected geometry reuses the original 300-DPI source raster;
- missing or unreadable scratch causes normal v4 render/build/gate work to run again.

Presentation render assembly calls the same wrapped geometry delegate and therefore reuses the prior decision/raster instead of recomputing it.

### Temporary scratch boundary

Large 300-DPI rasters are not retained in the whole-document Python object graph. They are written losslessly as local `.npy` scratch files under a temporary run directory.

The scratch directory:

- is process/run local;
- is deleted when the top-level S0 call completes or fails;
- is never uploaded to object storage;
- is never exposed through a source reference;
- is not a durable artifact or business record.

This deliberately trades bounded local disk I/O for lower CPU duplication and bounded RSS. The benchmark must verify that scratch I/O does not become the next dominant cost. If it does, the next optimization should preserve pixel identity while reducing scratch traffic rather than reintroducing duplicate rendering.

### Existing bounded-v4 chunking remains

The 16-page ordinary-v4 chunk coordinator remains the memory boundary.

Phase 1 replaces only its base page processor with a shared-aware processor. Chunk-local provider page indexes are translated back to original source page numbers before evidence lookup.

If page mapping or evidence is unavailable, processing falls back to the existing OpenCV v4 path.

## Quality invariants

Phase 1 must not change:

- presentation page-role vocabulary;
- presentation model/provider behavior;
- presentation confidence threshold;
- high-resolution presentation confirmation;
- continuous-body-prose conflict protection;
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

## Phase 0 observability remains outermost

Installation order in Staging is:

```text
existing production-equivalent overlays
  -> bounded v4 compatibility
  -> S0 v5 Phase 1 shared analysis
  -> cheap shadow geometry
  -> S0 v5 Phase 0 observability
  -> bound pdf_ingestion imports
```

Keeping Phase 0 profiling outside Phase 1 is intentional. Its render/build/gate counters therefore measure actual expensive calls after sharing rather than logical page visits.

## Runtime acceptance gate

CI passing is necessary but is not sufficient to validate Phase 1.

After the candidate is deployed to Staging, rerun the exact locked 100-page benchmark and compare with Phase 0.

Required evidence:

1. `render_120_count` moves from `200` toward `100`.
2. `render_300_count` moves from `200` toward `100` for this raster-heavy fixture.
3. Geometry build/gate calls are no longer duplicated for the same relevant source pages.
4. `changed_page_count` remains consistent with the Phase 0 result (`99`) unless a concrete page-level quality review explains a difference.
5. Presentation classification behavior remains equivalent on known presentation/mixed pages.
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

including ordinary structure/color/geometry cache hits and presentation geometry reuse.

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
