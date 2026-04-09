#!/usr/bin/env python3
"""
Generate BIDS events.tsv files for MonoDep project.

Tasks:
  1. task-eyedep (MAIN): 2 runs x 242 vols, block design (8s blocks)
     Conditions: Left, Right, Both
     Fixed design, same for all subjects and sessions.

  2. task-loc (LOC): 4 runs x 170 vols, block design (24s blocks)
     Conditions: Left, Right
     Fixed design, alternating pattern.

  3. task-rest: no events needed (resting state)

Usage:
  python generate_events.py <bids_dir>
"""

import os, sys, json, glob, argparse

# =============================================
# task-eyedep: 2 runs, 3 conditions, 8s blocks
# =============================================
EYEDEP_BLOCK_DUR = 8.0

EYEDEP_RUNS = [
    {  # run-01
        'Left':  [0, 100, 140, 180, 280, 320, 400, 440],
        'Right': [20, 60, 160, 220, 260, 300, 380, 460],
        'Both':  [40, 80, 120, 200, 240, 340, 360, 420],
    },
    {  # run-02
        'Left':  [20, 60, 140, 180, 280, 320, 360, 460],
        'Right': [0, 80, 160, 200, 240, 300, 400, 440],
        'Both':  [40, 100, 120, 220, 260, 340, 380, 420],
    },
]

# =============================================
# task-loc: 4 runs, 2 conditions, 24s blocks
# =============================================
LOC_BLOCK_DUR = 24.0

LOC_RUNS = [
    {  # run-01
        'Left':  [24, 72, 120, 168, 216, 264],
        'Right': [48, 96, 144, 192, 240, 288],
    },
    {  # run-02
        'Left':  [48, 96, 144, 192, 240, 288],
        'Right': [24, 72, 120, 168, 216, 264],
    },
    {  # run-03
        'Left':  [24, 72, 120, 168, 216, 264],
        'Right': [48, 96, 144, 192, 240, 288],
    },
    {  # run-04
        'Left':  [48, 96, 144, 192, 240, 288],
        'Right': [24, 72, 120, 168, 216, 264],
    },
]


def write_events_tsv(filepath, events):
    """Write events to BIDS-compliant TSV."""
    cols = ['onset', 'duration', 'trial_type']
    with open(filepath, 'w') as f:
        f.write('\t'.join(cols) + '\n')
        for e in sorted(events, key=lambda x: x['onset']):
            f.write(f"{e['onset']}\t{e['duration']}\t{e['trial_type']}\n")


def generate_task_events(run_def, block_dur):
    """Generate event list from run definition."""
    events = []
    for trial_type, onsets in run_def.items():
        for onset in onsets:
            events.append({
                'onset': float(onset),
                'duration': block_dur,
                'trial_type': trial_type,
            })
    return events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('bids_dir')
    parser.add_argument('--dry_run', action='store_true')
    args = parser.parse_args()

    bids_dir = args.bids_dir
    n_written = 0

    for sub_dir in sorted(glob.glob(os.path.join(bids_dir, 'sub-*'))):
        sub = os.path.basename(sub_dir)
        for ses_dir in sorted(glob.glob(os.path.join(sub_dir, 'ses-*'))):
            ses = os.path.basename(ses_dir)
            func_dir = os.path.join(ses_dir, 'func')
            if not os.path.isdir(func_dir):
                continue

            # task-eyedep events
            for run_idx, run_def in enumerate(EYEDEP_RUNS, start=1):
                bold = os.path.join(func_dir, f'{sub}_{ses}_task-eyedep_run-{run_idx:02d}_bold.nii.gz')
                if not os.path.exists(bold):
                    continue
                fname = f'{sub}_{ses}_task-eyedep_run-{run_idx:02d}_events.tsv'
                fpath = os.path.join(func_dir, fname)
                events = generate_task_events(run_def, EYEDEP_BLOCK_DUR)
                if args.dry_run:
                    print(f"  would write: {fname}")
                else:
                    write_events_tsv(fpath, events)
                    print(f"  wrote: {fname}")
                    n_written += 1

            # task-loc events
            for run_idx, run_def in enumerate(LOC_RUNS, start=1):
                bold = os.path.join(func_dir, f'{sub}_{ses}_task-loc_run-{run_idx:02d}_bold.nii.gz')
                if not os.path.exists(bold):
                    continue
                fname = f'{sub}_{ses}_task-loc_run-{run_idx:02d}_events.tsv'
                fpath = os.path.join(func_dir, fname)
                events = generate_task_events(run_def, LOC_BLOCK_DUR)
                if args.dry_run:
                    print(f"  would write: {fname}")
                else:
                    write_events_tsv(fpath, events)
                    print(f"  wrote: {fname}")
                    n_written += 1

    print(f"\nDone. {n_written} events.tsv files written.")


if __name__ == '__main__':
    main()
