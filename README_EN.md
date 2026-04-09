# DICOM-to-BIDS Conversion Skill

> An end-to-end workflow distilled from four completed projects:
> ODLoc, EYEDEP_CRF, MP_CRF, and MonoDep.
> The goal is to make MRI DICOM-to-BIDS conversion usable by general AI agents, not only by human operators.

Chinese documentation lives in [README.md](README.md).

This repository is an agent-oriented MRI DICOM-to-BIDS workflow/skill package, not just a single script bundle. It includes:

- a skill entrypoint: `SKILL.md`
- an optional Codex metadata example: `agents/openai.yaml`
- reusable shell and Python scripts
- templates, references, and sanitized examples

You do not need Codex to use this repository. The core workflow is driven by standard CLI scripts and documentation. Any agent that can execute shell commands, read/write files, parse basic JSON, and pause for a few user decisions can integrate with it.

## What It Covers

- scouting `SeriesDescription` variants before writing `dcm2bids_config.json`
- generating `participants_mapping.tsv`
- parallel conversion with `dcm2bids`
- validating file counts, functional run volumes, and unmatched tmp outputs
- cleaning aborted runs
- copying physio or behavior files into `sourcedata`
- scaffolding `events.tsv` generation for task fMRI

## Expansion Areas

The current strongest path is Siemens-style fMRI data, while the following areas are explicit extension targets:

- Philips and GE vendor-specific conversion patterns
- mature templates for DWI, ASL, and multi-echo GRE
- higher-automation flows with fewer required user decisions

## Quick Start

1. Check dependencies:

```bash
dcm2bids --version
dcm2niix -h
python3 --version
```

2. Create a project workspace:

```bash
SKILL_DIR="<path-to-this-repo>"
PROJECT_DIR="<project-root>"

mkdir -p "$PROJECT_DIR/code" "$PROJECT_DIR/bids"
cp "$SKILL_DIR/templates/project_config.yaml" "$PROJECT_DIR/code/project_config.yaml"
cp "$SKILL_DIR/templates/decision_log.md" "$PROJECT_DIR/code/decision_log.md"
```

3. Scout representative sessions before writing config:

```bash
bash "$SKILL_DIR/scripts/scout.sh" <dicom_session_folder> /tmp/scout_example
```

4. Run conversion after preparing `dcm2bids_config.json` and `participants_mapping.tsv`:

```bash
bash "$SKILL_DIR/scripts/convert_parallel.sh" "$PROJECT_DIR"
```

5. Validate outputs:

```bash
python3 "$SKILL_DIR/scripts/validate.py" "$PROJECT_DIR/bids" \
  --expected-anat 7 --expected-func 7 --expected-fmap 7 \
  --json --fail-on-anomaly
```

## Recommended Environment

| Tool | Version | Purpose |
|------|---------|---------|
| `dcm2bids` | >= 3.2.0 | DICOM to BIDS conversion |
| `dcm2niix` | >= v1.0.20211006 | DICOM to NIfTI |
| `python3` | >= 3.8 | Validation and post-processing scripts |
| `bash` / `zsh` | — | Parallel shell execution |

## Agent Compatibility

Best fit:

- shell execution
- file read/write
- basic JSON parsing
- limited interactive user confirmation
- tolerance for longer-running batch jobs

Helpful integration features:

- support for non-zero exit codes
- support for JSON stdout from validation scripts
- ability to pause on user decision points

## Safety And Privacy

- Do not put direct identifiers into `participants_mapping.tsv`.
- Keep examples de-identified.
- Use `cleanup_aborted.py --dry-run --json` before destructive cleanup in automation.
- When rerunning a session after config changes, remove the old BIDS output for that session first.

## Automation-Friendly Interfaces

- `validate.py --json --fail-on-anomaly`
- `cleanup_aborted.py --dry-run --json --fail-if-found`
- `cleanup_aborted.py --yes` for non-interactive confirmation

## Minimal Public Demo

This repo includes a synthetic smoke demo with no real MRI data:

```bash
python3 scripts/create_synthetic_bids_demo.py /tmp/bids-convert-demo --with-aborted
python3 scripts/validate.py /tmp/bids-convert-demo --json
python3 scripts/cleanup_aborted.py /tmp/bids-convert-demo --dry-run --json --fail-if-found
```

See `examples/smoke-demo/README.md` for details.

## Expansion Roadmap

The current strongest path comes from Siemens-style fMRI projects, but that is a starting point rather than a hard boundary. The long-term direction is to keep one stable workflow skeleton and progressively extend it to Philips, GE, and additional MRI sequence families instead of duplicating separate end-to-end pipelines.

See `references/extension_roadmap.md` for the detailed roadmap.

## Repository Layout

```text
bids-convert/
  SKILL.md
  README.md
  README_EN.md
  agents/
    openai.yaml
  scripts/
  templates/
  references/
  examples/
    smoke-demo/
  tests/
```

## Notes For Release

- Current public version: `v1.0.0`
- Release notes: [RELEASE_NOTES_v1.0.0.md](RELEASE_NOTES_v1.0.0.md)
- License: [MIT](LICENSE)
