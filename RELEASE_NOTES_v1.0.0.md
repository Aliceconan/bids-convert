# v1.0.0

First public release of the DICOM-to-BIDS conversion skill/workflow package.
This version is grounded in Siemens-style fMRI projects, while intentionally preserving a path to future Philips, GE, and broader sequence-type support.

## Included

- End-to-end workflow documentation for DICOM to BIDS conversion
- Shell/Python scripts for scouting, parallel conversion, validation, cleanup, auxiliary copying, and events scaffolding
- Templates and references extracted from four completed projects
- A standard `SKILL.md` entrypoint plus optional Codex metadata
- Structured JSON output for validation and aborted-run cleanup scripts
- Minimal smoke tests and GitHub Actions CI
- A synthetic public demo for quick validation without MRI data
- An explicit roadmap for extending the workflow beyond the current Siemens-first backbone

## Intended users

- AI agents that can execute shell commands, read/write files, and pause for user confirmation
- Human operators who want a documented, semi-automated dcm2bids workflow

## Known limits

- Strongest coverage is currently Siemens-style fMRI projects with MP2RAGE, EPI BOLD, and reverse-PE fieldmaps
- Philips, GE, DWI, ASL, and richer paradigm ingestion are planned extension areas rather than frozen non-goals
- The workflow still expects human confirmation at critical decision points

## Suggested git commands

Once this folder is inside a git repository and committed:

```bash
git add .
git commit -m "Release v1.0.0"
git tag -a v1.0.0 -m "v1.0.0"
git push origin <branch-name> --tags
```
