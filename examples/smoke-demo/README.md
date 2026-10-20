# Synthetic Smoke Demo

This demo does not use real MRI data. It creates a tiny synthetic BIDS-like tree so you can verify:

- `scripts/validate.py`
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

## Aborted runs

Without a protocol table `validate.py` only reports the volume distribution — it never guesses which run is
aborted from the data (that guess deletes good runs in variable-length paradigms, pitfalls #40). Real projects
declare expected volumes in `code/protocol.tsv` and let `finalize.py` handle aborted runs; see `tests/test_finalize.py`
for synthetic end-to-end cases.

If you want a clean demo without an aborted run:

```bash
python3 scripts/create_synthetic_bids_demo.py /tmp/bids-convert-demo-clean
```
