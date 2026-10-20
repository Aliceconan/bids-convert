# DICOM-to-BIDS Conversion Skill

> End-to-end workflow distilled from four completed projects (ODLoc / EYEDEP_CRF / MP_CRF / MonoDep)
> and the HS7T movie-fMRI project (2026). Any AI agent that can run shell commands, read/write files,
> and pause for user decisions can execute it.

中文版: [README.md](README.md)

An agent-oriented MRI DICOM-to-BIDS workflow package, not a single script:

- skill entrypoint: `SKILL.md` (single source of truth for the full workflow)
- Python CLI scripts (standard library only, Python 3.6 compatible; scouting and DICOM-embedded physio also need pydicom)
- project-declaration templates, references, and examples abstracted from real projects
- optional agent-platform metadata example: `agents/openai.yaml`

**Core design**: every human decision lives in declaration files (`project.json` / `protocol.tsv` /
`decisions.tsv` / dcm2bids config), so one command reproduces the same BIDS from DICOM. Each session can be
previewed with the real dcm2bids before converting any image. Whenever something cannot be decided
automatically, the scripts stop without touching any file and list what a human must decide.

## Quick Start

```bash
SKILL_DIR="<path-to-this-repo>"
PROJECT_DIR="<project-root>"
PY_DCM="<python of the env where dcm2bids + pydicom are installed>"

# 1. init: copy templates, write participants_mapping.tsv (participant_id, [session], dicom_dir, [physio_mode])
mkdir -p "$PROJECT_DIR/code"
cp "$SKILL_DIR"/templates/{project.json,protocol.tsv,decisions.tsv,dcm2bids_config.json,decision_log.md} "$PROJECT_DIR/code/"

# 2. scout: one row per series + cross-session summary (naming variants, volume counts)
$PY_DCM "$SKILL_DIR/scripts/scout.py" "$PROJECT_DIR"

# 3. write config / protocol / project.json, then lint
python3 "$SKILL_DIR/scripts/lint_config.py" "$PROJECT_DIR/code/dcm2bids_config.json" --fix

# 4. preview (no image conversion): what each series becomes, which sessions need a decision
python3 "$SKILL_DIR/scripts/preview.py" "$PROJECT_DIR"

# 5. convert: dcm2niix cache -> dcm2bids -> finalize (run numbers / discards / fmap pairing / TaskName) -> physio
$PY_DCM "$SKILL_DIR/scripts/convert.py" "$PROJECT_DIR"

# 6. checks, dataset metadata, BIDS compliance
python3 "$SKILL_DIR/scripts/validate.py" --project "$PROJECT_DIR" --json --fail-on-anomaly
python3 "$SKILL_DIR/scripts/init_metadata.py" "$PROJECT_DIR"
npx bids-validator "$PROJECT_DIR/bids" --ignoreNiftiHeaders
```

## Dependencies

| Tool | Version | Purpose |
|------|---------|---------|
| `dcm2bids` | 3.2.x (Python ≥3.7 is fine) | series matching and naming |
| `dcm2niix` | ≥ v1.0.20211006 | DICOM → NIfTI |
| `python3` | ≥ 3.6 | all scripts (standard library only) |
| `pydicom` | 2.x | `scout.py`, DICOM-mode physio (use the dcm2bids environment) |
| `npx bids-validator` | — | final compliance check (run it on a machine that mounts the data if the server has no node) |

`dcm2bids --skip_dcm2niix` is not needed (it requires Python ≥3.8); `convert.py` manages its own dcm2niix cache.

## Safety And Privacy

- The mapping and decisions files never contain names, original IDs or birth dates; whether `participants.tsv` gets age/sex is the user's call.
- Never commit real DICOM or identifiable information; examples contain only series names and anonymous IDs.
- Discarded files are moved to `work/discarded/` with a reason, never deleted; `finalize.py` is dry-run by default.
- Re-running `convert.py` for a session after changing the config or decisions is safe (it re-matches from the cache every time: no leftovers, no data loss).

## Validation And Automation

- `convert.py`: exit 0 all done / 2 some sessions need a human decision / 1 failures; details in `code/logs/convert_<time>.json`
- `preview.py`, `finalize.py`: exit 2 when decisions are pending, without changing any file
- `validate.py --json --fail-on-anomaly`, `lint_config.py --json`

Tests (Python 3.6+, no real images needed):

```bash
python3 -m unittest discover -s tests
```

## Minimal Demo

```bash
python3 scripts/create_synthetic_bids_demo.py /tmp/bids-convert-demo --with-aborted
python3 scripts/validate.py /tmp/bids-convert-demo --json
```

See `examples/smoke-demo/README.md`.

## Repository Layout

```text
bids-convert/
  SKILL.md        full workflow (single source of truth)
  scripts/        scout / lint_config / preview / convert / finalize / physio_to_bids /
                  validate / init_metadata / copy_sourcedata / generate_events_template / bids_common
  templates/      project.json  protocol.tsv  decisions.tsv  dcm2bids_config*.json  decision_log.md
  references/     project_spec  workflow  pitfalls  mp2rage_cheatsheet  project_diffs  agent_integration  extension_roadmap
  examples/       HS7T-movie (complete declaration set)  ODLoc  MonoDep  smoke-demo
  tests/
```

References are written in Chinese; `references/project_spec.md` documents the declaration formats and
fieldmap-pairing rules, `references/pitfalls.md` lists 44 known pitfalls (silent dcm2bids behaviours,
Siemens/CMRR specifics, bids-validator errors).

## Version History

| Version | Date | Changes |
|------|------|------|
| v1.0 | 2026-04-09 | initial release, four projects |
| v1.1 | 2026-09-15 | Siemens CMRR physio support |
| v2.0 | 2026-10-19 | declarative rewrite: project.json / protocol.tsv / decisions.tsv; header-only scout, real-dcm2bids preview, cached conversion (fixes the old `--rerun` that silently produced nothing), finalize (run = protocol position, time-based fmap pairing, TaskName, recoverable discards), time-based physio pairing; config must declare `case_sensitive` / `bids_uri` / `TaskName`; Python 3.6 compatible. See RELEASE_NOTES_v2.0.0.md |
