# Agent notes for Starplot

## Data build after translation changes

The translated name tables (`star_designations`, `constellation_names`, `dso_names`)
are compiled into `data/build/` and copied to `src/starplot/data/library/` as
`*.parquet` files. These files are ignored by git because of `*.parquet` in
`.gitignore`.

If a new locale is added under `data/raw/translations/`, the parquet files in
the working tree may become stale and tests will fail with errors like:

```text
ibis.common.exceptions.IbisTypeError: Column 'name_it' is not found in table.
```

Regenerate the data with:

```bash
conda activate skytools  # or the appropriate environment
PYTHONPATH=src python data/scripts/db.py
```

This writes new `.parquet` files to `data/build/` and copies them to
`src/starplot/data/library/`, at which point all translation-dependent tests
should pass.

## Key verification commands

```bash
# Python interactive / visual-parity tests
PYTHONPATH=src python -m pytest tests/test_interactive/ tests/test_visual_parity/ -q

# Full Python test suite
PYTHONPATH=src python -m pytest tests/ -q

# Browser runtime tests
cd web && npm test

# Lint changed Python files
python -m ruff check <paths>
```
