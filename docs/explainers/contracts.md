# Contracts

## What it does

`src/evident/contracts/` holds the Pydantic models that every stage reads and writes: facts and their sources, documents, targets and coverage rows, content plans and claims, validation results, outputs and run status. They are the single source of truth for data shapes. Anything that arrives from a model, a file or a client is parsed into one of these before it goes anywhere else.

## Why it is built this way

- **Strict, closed, versioned.** The design's "Data model" section says all contracts use strict types, enums and a `schema_version`. Every contract subclasses `Contract` (`strict=True`, `extra="forbid"`, `frozen=True`), so a string where a number belongs, an unknown field or a mutated record all fail loudly. This supports the "validate all model JSON against the contract" rule and the fail-closed principle.
- **Frozen instances.** A fact version is never edited in place. Editing creates a new version (see "Lineage" and the state machines in the design), so immutability matches the domain.
- **One source variant per fact.** The "Source variants" table gives six location shapes. They are a union discriminated on `extraction_path`, so a fact cannot carry fields from two variants, and receipts can pick the right renderer from the type.
- **Controlled metric vocabulary.** `metric` must be in `METRIC_VOCAB` or start with `other:`. Layer 1 binds numbers to metric records, so free-form names would make binding ambiguous. `other:` metrics are accepted here and routed to user review later.
- **Year-month dates.** `start` and `end` use `YYYY-MM`, which the date and duration checks rely on.
- **Added fields.** `title` and `organisation` on attributes serve the entity check and extraction scoring. `span_found` and `bbox_verified` record whether the quoted span or box was actually confirmed against the document.
- **Enums accept plain strings.** Strict mode would otherwise require enum instances for Python dict input. A small base class (`ContractEnum`) converts a valid string to the enum and still rejects invalid values.

## How the model is used

Not at all. The contracts contain no model calls. They are the target that model output is validated against: extraction, coverage grading, planning and the judge each return JSON that must parse into these types before anything else happens.

## Limits

- They check shape, not truth. A well-formed fact can still be wrong; grounding is the job of validation layers 1 and 2.
- `bbox` coordinates, `char_start`/`char_end` and `start_ms`/`end_ms` are not checked for ordering or range. That needs the source document.
- `ErrorCategory` is re-exported from `evident.errors`, not redefined.
- Contracts are frozen. Any change needs owner approval and a `schema_version` bump.

## Example

The demo fact `exp_03` (version 2, confirmed) is the design's example:

```json
{
  "fact_id": "exp_03", "version": 2, "status": "confirmed", "kind": "project",
  "text": "Built a FastAPI service serving a PyTorch skin-condition classifier",
  "attributes": {"ownership": "built", "deployment": "prototype", "start": "2026-05", "end": "2026-07", ...},
  "source": {"extraction_path": "pdf_text", "document_id": "doc_cv_01", "page": 1,
             "bbox": [72, 410, 540, 438], "span_found": true, ...}
}
```

`FactVersion.model_validate_json` accepts it. Changing `start` to `2026-13`, or `version` to `"2"`, raises a `ValidationError`. The full file is `tests/contracts/fixtures/fact_version.json`.
