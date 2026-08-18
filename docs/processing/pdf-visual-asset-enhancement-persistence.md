# Visual enhancement persistence mapping

Enhanced image bytes are not stored directly in relational columns. The existing Structured Content v2 persistence layer stores:

- the `AssetReferenceV2` record;
- rendition records associated with the asset;
- the enhanced `NORMALIZED` rendition record;
- the retained `OCR_SOURCE` rendition record;
- storage references and checksums for both byte objects;
- provider/model/prompt and cleanup status in asset metadata.

Persistence may reconstruct rendition IDs in database sort order rather than the order originally declared by the in-memory Candidate. Reader delivery therefore does not use rendition-ID order as the semantic preference contract. It ranks valid, available, safe renditions by role:

1. `NORMALIZED`;
2. `ORIGINAL`;
3. `OCR_SOURCE`;
4. `THUMBNAIL`.

The asset's reconstructed rendition-ID order is only a tie-breaker between renditions of the same role. Consequently, an enhanced `NORMALIZED` rendition remains Reader-preferred after persistence and reconstruction, while the `OCR_SOURCE` crop remains available as evidence and fallback.

This is the repository's existing durable-asset pattern: relational data identifies and audits the asset, while `StorageProvider` holds the binary PNG. Reader resolves the selected Candidate's database rendition record and then streams the referenced image bytes.
