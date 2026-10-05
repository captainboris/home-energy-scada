# AGENTS.md

This repository is the source of truth for Home Energy SCADA.

## Before changing code

Read these files before implementation:

1. `docs/PRODUCT_FACT_SHEET.md`
2. `docs/PRODUCT_SPEC.md`
3. `docs/UI_BEHAVIOUR_SPEC.md`
4. `docs/DATA_SEMANTICS.md`
5. `docs/REGRESSION_CHECKLIST.md`

Treat every request as an incremental change unless the task explicitly says
that an architecture migration or product-contract change is intended.

## Product facts are protected defaults

`docs/PRODUCT_FACT_SHEET.md` is the short-form list of current behaviours and
architecture boundaries that must not be changed accidentally.

Before editing:

- identify which Fact Sheet sections the task touches;
- preserve unrelated facts;
- do not silently reinterpret data semantics, interaction behaviour or layout;
- do not modify protected ingestion / infrastructure boundaries unless the task
  explicitly includes them.

If the requested change intentionally conflicts with a Fact Sheet item, state
that conflict before implementation and update the Fact Sheet, the relevant
living specification, tests and `docs/CHANGELOG.md` in the same change.

## Git workflow

Do not develop directly on `main`.

Use a short-lived `feature/`, `fix/`, `docs/`, `chore/` or `hotfix/`
branch, open a Pull Request, and let required CI pass before merge.

## Validation

Run the suites relevant to the change. For product behaviour changes, work
through `docs/REGRESSION_CHECKLIST.md` and report PASS / FAIL / NOT TESTED
truthfully. Browser/device behaviour must not be marked PASS based only on
source inspection or jsdom tests.
