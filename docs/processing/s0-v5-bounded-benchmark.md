# S0 v5 bounded benchmark protocol

## Purpose

The legacy S0/OpenCV path is too expensive and unreliable to require a complete
large-document run before S0 v5 work can proceed. A 528-page source has already
shown multi-hour runtime and repeated incomplete processing. The engineering
baseline therefore uses a bounded, reproducible 100-page sample instead of a
full legacy rerun.

This protocol is staging-only benchmarking guidance. It does not change the
production processing contract and it must not be used to claim that an
incomplete legacy run failed because of OOM unless direct termination evidence
shows that cause.

## Sampling contract

For a source PDF with at least 100 pages, select exactly 100 original pages:

- first 5 pages are mandatory;
- last 5 pages are mandatory;
- known special/problem pages may be added as mandatory pages;
- remaining slots are selected with seeded stratified random sampling across the
  remaining source pages;
- selected pages stay in original document order;
- the same seed and source page count must produce the same selection;
- the benchmark manifest records the source SHA-256, seed, selected original
  page numbers, sample-to-original page mapping, and a selection digest.

For sources smaller than 100 pages, every page is selected.

The default seed is `atlas-s0-v5-benchmark-v1`. Do not change the seed between
legacy v4 and S0 v5 comparisons for the same benchmark source.

## Build the sample

From the repository root:

```bash
python scripts/build_s0_benchmark_sample.py /path/to/book.pdf
```

For the 528-page benchmark, optional known problem pages can be forced into the
sample without giving up stratified coverage:

```bash
python scripts/build_s0_benchmark_sample.py /path/to/book.pdf \
  --sample-size 100 \
  --seed atlas-s0-v5-benchmark-v1 \
  --special-pages 302
```

The command writes a sampled PDF and a JSON manifest next to it by default. The
sample builder copies selected PDF page objects; it does not render the pages or
run OpenCV, so sampling itself does not lower raster quality.

## Locked benchmark identity — 2026-08-18

The initial large-book benchmark is now locked and must not be regenerated for
comparisons between current v4, S0 v5, and later Modal execution:

- source page count: `528`;
- source byte size: `65,445,424` bytes;
- source SHA-256:
  `3124d61a5c7ce6828cd7dd77277fa9c8d192ea6047816ff8af43892ba936e121`;
- sample size: `100` pages;
- seed: `atlas-s0-v5-benchmark-v1`;
- mandatory diagnostic page: original page `302`;
- selection digest:
  `c9be9e6600c71860357d4173b1715b2fae44d80ef826c77f2cc2bf6339660c1a`.

Representative sample-to-original mappings were rendered and compared after
sample construction. Original pages 1, 252, 302, and 528 matched sample pages
1, 48, 57, and 100 pixel-for-pixel at the verification render resolution. The
JSON manifest remains the authority for the complete 100-page mapping.

## Source raster structure discovery

Native PDF inspection of the locked 528-page source established an important
S0 v5 optimization opportunity:

- all 528 pages contain exactly one embedded image;
- that image covers essentially the full PDF page on every page;
- all embedded page images are `701 x 1084` pixels;
- effective source resolution is approximately `150 DPI` in both dimensions;
- 526 embedded page images are PNG and 2 are JPEG;
- the source has no native text layer on the benchmark pages inspected.

For this corpus, the current universal 300-DPI PDF-page rendering step therefore
upsamples a roughly 150-DPI source raster by about 2x in each dimension, or about
4x in pixel count, before the high-cost OpenCV work. That render cannot create
new source detail. This does **not** by itself prove that replacing current v4
with native-raster processing is quality-equivalent; it establishes a concrete
candidate for shadow measurement and quality comparison.

S0 v5 must consequently treat a **Native Full-Page Raster Fast Path** as a
first-class design option. Native inspection should record the embedded raster
pixel dimensions and effective DPI. Cheap inspection can be derived from that
native raster, and pages selected for heavy treatment can be tested at native
source resolution instead of blindly rendering the PDF page at 300 DPI.

A local, environment-specific decode/render microbenchmark on the locked
100-page sample produced the following directional measurements:

- PyMuPDF 120-DPI page render: about `1.184 s` total, median `11.1 ms/page`;
- PyMuPDF 300-DPI page render: about `4.103 s` total, median `40.25 ms/page`;
- direct native embedded-raster decode via `fitz.Pixmap(document, xref)`: about
  `0.773 s` total, median `5.99 ms/page` and p95 about `17.15 ms/page`.

These are developer-machine diagnostics, not production SLOs. Runtime decisions
must be based on Staging telemetry and quality validation from the same locked
sample.

## Required comparison discipline

Use the exact same sampled PDF and manifest for:

1. bounded legacy/current-v4 measurement;
2. S0 v5 planner validation;
3. S0 v5 selective-preprocessing measurement;
4. later Modal CPU measurements.

Do not regenerate the sample between implementations. Treat `source_sha256`,
`seed`, and `selection_digest` as the benchmark identity.

## Legacy baseline policy

A full 528-page legacy run is **not** a prerequisite for S0 v5 development.
Record existing large-book evidence as the observed legacy baseline and use the
100-page sample only for bounded measurements.

If the 100-page legacy sample still takes an excessive amount of time, stop at a
pre-declared benchmark time budget and retain the partial stage/page timings.
That timeout must not block implementation of work-elimination changes.

## Metrics

At minimum, compare:

- total S0 wall time;
- 120-DPI/cheap render count and time;
- 300-DPI render count and time;
- geometry candidate count and time;
- background cleanup count and time;
- changed page count;
- PDF assembly/serialization time;
- peak RSS;
- source/artifact bytes transferred where available;
- completion or precise failure/termination evidence.

For S0 v5 also record planner routes, native-full-page-raster candidates, and the
number of pages that avoid 300-DPI processing.

## Quality review

Performance alone is not sufficient. The benchmark sample plus mandatory known
problem pages should cover, where present:

- clean white pages;
- gray scanner background;
- skew/perspective cases;
- dark foreground content;
- diagrams/tables/long lines;
- photo or color-critical pages;
- presentation-like pages;
- orientation-risk pages;
- born-digital pages.

False-positive heavy treatment is acceptable during conservative rollout. A
page that the planner marks as safe passthrough when high-resolution treatment
is actually required is the failure mode to minimize.

## Full-document acceptance

The 528-page original remains the final runtime acceptance source for the new
architecture. Legacy v4 is not required to complete it first. S0 v5 must prove
that it can finish the full document and report its actual heavy-page count,
300-DPI render count, native-raster fast-path count, wall time, peak RSS, and
output-quality checks.
