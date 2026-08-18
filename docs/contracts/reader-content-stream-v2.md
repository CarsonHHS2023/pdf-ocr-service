# Reader Content Stream Protocol v2

| Field | Value |
|---|---|
| Document Type | Contract |
| Version | v2 |
| Authority Domain | Reader content stream protocol markers, behavior, and compatibility |
| Applies To | Plain text document content streams rendered by `pdf-ocr-service` for the Reader |

## Purpose

Reader Content Stream Protocol v2 defines the plain text stream consumed by the Reader for document content rendered by `pdf-ocr-service`. It formalizes the existing paragraph and image marker behavior and adds heading markers for heading levels 1 through 6.

This protocol does not change the current storage architecture or API contract. It is intentionally independent of internal storage and implementation details.

## Protocol summary

The stream is plain text. Logical lines are delimited by `\n`.

Protocol v2 supports three content forms:

1. Paragraph lines.
2. Heading lines.
3. Image marker lines.

No JSON blocks are introduced.

## Current compatibility baseline

Version 1 streams remain valid v2 streams when they contain only:

- plain text paragraphs
- paragraph delimiters using `\n`
- image markers

The existing image marker is unchanged:

```text
$%$%$%{image_id}$%$%$%
```

For example:

```text
$%$%$%image_123$%$%$%
```

## Heading markers

Version 2 adds heading markers for levels 1 through 6:

```text
$#$#1
$#$#2
$#$#3
$#$#4
$#$#5
$#$#6
```

A heading marker is valid only when it appears at the beginning of a logical line and is immediately followed by heading text. The heading terminates at the next `\n`.

Examples:

```text
$#$#1Chapter One
$#$#2Introduction
$#$#3Background
```

### Heading rules

- Heading markers are valid only at the beginning of a logical line.
- Heading markers are immediately followed by heading text.
- Heading text terminates at `\n`.
- Levels 1 through 6 are reserved for headings.
- Unknown levels should be rendered as normal text.
- Readers that do not understand heading markers may display them literally.

## Paragraphs

A normal paragraph is serialized as plain text and terminated by `\n`.

```text
This is a paragraph.
```

Paragraph rules:

- Internal line breaks are removed before serialization.
- Each paragraph ends with `\n`.
- Paragraph content has no required marker prefix.
- Old paragraph-only streams remain valid.

## Images

Images use the existing image marker format and occupy an entire logical line:

```text
$%$%$%image_123$%$%$%
```

Image rules:

- Image markers occupy an entire logical line.
- The image marker format is unchanged from the current protocol.
- The marker content between delimiters identifies the image.

## Compatibility

Old streams without heading markers remain valid v2 streams.

Readers that do not understand heading markers may display those markers literally. This keeps generated content backward compatible while allowing newer Readers to render headings semantically.

Recommended deployment order:

1. Deploy Reader support for heading markers.
2. Deploy backend heading generation.

This order prevents users from seeing heading markers literally in clients that are expected to support v2 rendering.

## Future compatibility

Future implementations may internally use richer representations such as:

- Nodes
- Blocks
- Document models

Those internal representations can still serialize into Reader Content Stream Protocol v2. The protocol defines the stream boundary between backend content generation and Reader rendering; it does not require or prohibit any specific internal storage model.

## Complete examples

### Chapter with section, paragraph, and image

```text
$#$#1Chapter One
$#$#2Introduction
This is the opening paragraph for the chapter. It has been normalized so that internal line breaks are removed.
$%$%$%image_123$%$%$%
This paragraph follows the image and continues the chapter narrative.
```

### Multiple headings before body text

```text
$#$#1Part I
$#$#2Chapter Two
$#$#3Historical Background
The section begins here with a normal paragraph.
```

### Deep heading hierarchy

```text
$#$#1Technical Reference
$#$#2Content Streams
$#$#3Markers
$#$#4Headings
$#$#5Reserved Levels
$#$#6Level Six Example
Heading levels one through six are reserved by the protocol.
```

### Mixed content with repeated images

```text
$#$#1Illustrated Chapter
This paragraph introduces the first figure.
$%$%$%image_cover$%$%$%
$#$#2Figure Discussion
This paragraph explains the previous image.
$%$%$%image_detail_001$%$%$%
This paragraph concludes the section.
```

### Unknown heading level rendered as normal text

```text
$#$#7Appendix Candidate
This line starts with an unknown heading level marker, so v2 Readers should render it as normal text.
```

## Non-goals

This protocol does not define:

- database schema
- Node model
- Document model
- LLM output
- OCR implementation
- API versioning
