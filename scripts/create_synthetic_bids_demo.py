#!/usr/bin/env python3
"""
Create a tiny synthetic BIDS-like dataset for smoke testing public scripts.

This is not valid MRI content and is only intended to exercise automation,
JSON outputs, and basic CLI flows without sharing real data.
"""

import argparse
import gzip
import json
import os
import shutil
import struct


def make_nifti_gz(path, volumes):
    header = bytearray(352)
    dims = [4, 64, 64, 36, volumes, 1, 1, 1]
    struct.pack_into("<8h", header, 40, *dims)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wb") as handle:
        handle.write(header)


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Create a synthetic BIDS demo dataset")
    parser.add_argument("output_dir", help="Where to create the demo dataset")
    parser.add_argument("--with-aborted", action="store_true",
                        help="Add a 1-volume aborted bold run")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite the output directory if it exists")
    args = parser.parse_args()

    if os.path.exists(args.output_dir):
        if not args.force:
            raise SystemExit(
                f"Output directory already exists: {args.output_dir} (use --force to overwrite)"
            )
        shutil.rmtree(args.output_dir)

    func_dir = os.path.join(args.output_dir, "sub-01", "ses-pre", "func")
    anat_dir = os.path.join(args.output_dir, "sub-01", "ses-pre", "anat")
    fmap_dir = os.path.join(args.output_dir, "sub-01", "ses-pre", "fmap")

    make_nifti_gz(os.path.join(anat_dir, "sub-01_ses-pre_T1w.nii.gz"), 1)
    write_json(os.path.join(anat_dir, "sub-01_ses-pre_T1w.json"), {"Modality": "MR"})

    make_nifti_gz(os.path.join(fmap_dir, "sub-01_ses-pre_dir-AP_epi.nii.gz"), 1)
    write_json(
        os.path.join(fmap_dir, "sub-01_ses-pre_dir-AP_epi.json"),
        {"PhaseEncodingDirection": "j"},
    )

    bold_01 = os.path.join(func_dir, "sub-01_ses-pre_task-loc_run-01_bold.nii.gz")
    make_nifti_gz(bold_01, 120)
    write_json(bold_01.replace(".nii.gz", ".json"), {"RepetitionTime": 2.0})

    if args.with_aborted:
        bold_02 = os.path.join(func_dir, "sub-01_ses-pre_task-loc_run-02_bold.nii.gz")
        make_nifti_gz(bold_02, 1)
        write_json(bold_02.replace(".nii.gz", ".json"), {"RepetitionTime": 2.0})

    print(f"Synthetic demo dataset created at: {args.output_dir}")
    if args.with_aborted:
        print("Included an aborted 1-volume bold run for cleanup testing.")


if __name__ == "__main__":
    main()
