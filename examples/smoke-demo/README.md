# Synthetic Smoke Demo

This demo does not use real MRI data. It creates a tiny synthetic BIDS-like tree so you can verify:

- `scripts/validate.py`
- `scripts/cleanup_aborted.py`
- JSON output handling in other agents or CI

## Create demo data

```bash
python3 scripts/create_synthetic_bids_demo.py /tmp/bids-convert-demo --with-aborted
```

This creates:

- one synthetic anat file
- one synthetic fmap file
- one normal bold run
- one optional aborted bold run

## Validate

```bash
python3 scripts/validate.py /tmp/bids-convert-demo --json
```

## Detect aborted runs

```bash
python3 scripts/cleanup_aborted.py /tmp/bids-convert-demo --dry-run --json --fail-if-found
```

If you want a clean demo without an aborted run:

```bash
python3 scripts/create_synthetic_bids_demo.py /tmp/bids-convert-demo-clean
```
