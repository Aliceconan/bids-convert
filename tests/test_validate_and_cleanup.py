#!/usr/bin/env python3
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def make_nifti_gz(path, volumes):
    header = bytearray(352)
    dims = [4, 64, 64, 36, volumes, 1, 1, 1]
    import struct
    struct.pack_into("<8h", header, 40, *dims)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wb") as handle:
        handle.write(header)


def extract_json(stdout):
    start = stdout.find("{")
    if start == -1:
        raise AssertionError(f"No JSON payload found in output:\n{stdout}")
    return json.loads(stdout[start:])


class ValidateAndCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="bids_convert_test_")
        self.bids_dir = os.path.join(self.tmpdir, "bids")
        self.func_dir = os.path.join(self.bids_dir, "sub-01", "ses-pre", "func")
        self.anat_dir = os.path.join(self.bids_dir, "sub-01", "ses-pre", "anat")
        self.fmap_dir = os.path.join(self.bids_dir, "sub-01", "ses-pre", "fmap")
        os.makedirs(self.func_dir, exist_ok=True)
        os.makedirs(self.anat_dir, exist_ok=True)
        os.makedirs(self.fmap_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_validate_reports_clean_dataset_as_json(self):
        make_nifti_gz(
            os.path.join(self.anat_dir, "sub-01_ses-pre_T1w.nii.gz"),
            volumes=1,
        )
        make_nifti_gz(
            os.path.join(self.fmap_dir, "sub-01_ses-pre_dir-AP_epi.nii.gz"),
            volumes=1,
        )
        bold_path = os.path.join(
            self.func_dir, "sub-01_ses-pre_task-loc_run-01_bold.nii.gz"
        )
        make_nifti_gz(bold_path, volumes=120)
        with open(bold_path.replace(".nii.gz", ".json"), "w") as handle:
            json.dump({"RepetitionTime": 2.0}, handle)

        result = subprocess.run(
            [
                sys.executable,
                os.path.join(REPO_ROOT, "scripts", "validate.py"),
                self.bids_dir,
                "--expected-anat",
                "1",
                "--expected-func",
                "1",
                "--expected-fmap",
                "1",
                "--json",
                "--fail-on-anomaly",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = extract_json(result.stdout)
        self.assertEqual(payload["summary"]["file_count_anomalies"], 0)
        self.assertEqual(payload["summary"]["volume_anomalies"], 0)
        self.assertEqual(payload["summary"]["tmp_unmatched"], 0)
        self.assertEqual(payload["summary"]["sessions_checked"], 1)

    def test_cleanup_detects_aborted_run_in_noninteractive_mode(self):
        good_run = os.path.join(
            self.func_dir, "sub-01_ses-pre_task-loc_run-01_bold.nii.gz"
        )
        bad_run = os.path.join(
            self.func_dir, "sub-01_ses-pre_task-loc_run-02_bold.nii.gz"
        )
        make_nifti_gz(good_run, volumes=120)
        make_nifti_gz(bad_run, volumes=1)
        with open(good_run.replace(".nii.gz", ".json"), "w") as handle:
            json.dump({}, handle)
        with open(bad_run.replace(".nii.gz", ".json"), "w") as handle:
            json.dump({}, handle)

        result = subprocess.run(
            [
                sys.executable,
                os.path.join(REPO_ROOT, "scripts", "cleanup_aborted.py"),
                self.bids_dir,
                "--dry-run",
                "--json",
                "--fail-if-found",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = extract_json(result.stdout)
        self.assertEqual(payload["summary"]["aborted_found"], 1)
        self.assertTrue(payload["summary"]["dry_run"])
        self.assertEqual(payload["expected_volumes"]["task-loc"], 120)


if __name__ == "__main__":
    unittest.main()
