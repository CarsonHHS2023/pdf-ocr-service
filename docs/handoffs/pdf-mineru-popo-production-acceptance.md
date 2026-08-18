# PDF MinerU-Popo production acceptance

After this branch is deployed, reprocess a PDF to create a new immutable
Structured Content v2 candidate. Existing selected candidates do not change.

Acceptance checks:

- repeated page headers, footers, and page numbers are absent from Reader v2 nodes;
- recovered headings retain `heading_level` and navigation hierarchy;
- TOC blocks become a list with one `list_item` per recovered entry;
- natural paragraphs remain separate nodes;
- an explicit paragraph continuation across adjacent physical pages becomes one
  node spanning both source units;
- Reader v2 receives these semantics without frontend text-pattern recovery.
