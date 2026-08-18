# PDF MinerU-Popo → SPR v2 convergence

The canonical production PDF path is:

```text
retained Paddle raw result
  -> normalized physical-page observations/evidence
  -> provider-independent MinerU/Popo PDF structure recovery
  -> validated SPR v2
  -> deterministic Structured Content v2 transformation
  -> explicit selection
  -> Reader v2
```

`app.processing.mineru_popo_pdf_recovery` has no database, storage, network,
Modal, Paddle runtime, legacy `PdfPage`, or `MineruResult` dependency. It consumes
only normalized source units, observations, anchors, and evidence.

The recovery stage owns semantic inference before SPR, including heading
hierarchy, TOC/list structure, page-furniture omission, visual/caption
association, and explicit cross-page paragraph continuation. The deterministic
Structured Content transformer and Reader v2 projection do not repeat that
inference.

Existing selected candidates remain immutable. Reprocessing creates a new
candidate and does not silently replace an existing explicit selection.
