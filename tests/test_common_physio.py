#!/usr/bin/env python3
"""bids_common（mapping/文件名/时间）与 physio_to_bids（按采集时间配对）的测试。"""
import json
import unittest
from pathlib import Path

from helpers import FakeProject, hms
import bids_common as bc
import physio_to_bids as P


class TestCommon(unittest.TestCase):
    def setUp(self):
        self.fp = FakeProject({"movie": [100, 120]})

    def tearDown(self):
        self.fp.cleanup()

    def test_mapping_without_session_column(self):
        spec = bc.load_project(str(self.fp.root))
        rows = bc.load_mapping(spec)
        self.assertEqual((rows[0]["sub"], rows[0]["ses"]), ("sub-01", ""))
        self.assertEqual(rows[0]["dicom_path"], Path(spec["raw_root"]) / "S0")
        self.assertEqual(rows[0]["physio_mode"], "none")

    def test_mapping_with_session_and_select(self):
        (self.fp.code / "participants_mapping.tsv").write_text(
            "participant_id\tsession\tdicom_dir\n01\tpre\t/a\n01\tpost\t/b\n02\tpre\t/c\n")
        spec = bc.load_project(str(self.fp.root))
        rows = bc.load_mapping(spec)
        self.assertEqual([(r["sub"], r["ses"]) for r in rows],
                         [("sub-01", "ses-pre"), ("sub-01", "ses-post"), ("sub-02", "ses-pre")])
        self.assertEqual(len(bc.select_rows(rows, ["sub-01"])), 2)
        self.assertEqual(len(bc.select_rows(rows, ["sub-01:ses-post"])), 1)
        with self.assertRaises(bc.SpecError):
            bc.select_rows(rows, ["sub-09"])

    def test_project_rejects_typos_and_missing_pairing(self):
        p = self.fp.code / "project.json"
        p.write_text(json.dumps({"fmap_pairng": "after"}))
        with self.assertRaises(bc.SpecError):
            bc.load_project(str(self.fp.root))
        p.write_text(json.dumps({}))
        with self.assertRaises(bc.SpecError):        # fmap_pairing 必填
            bc.load_project(str(self.fp.root))

    def test_names_and_time(self):
        e, s = bc.parse_name("sub-01_task-x_run-02_bold")
        self.assertEqual((e["run"], s), ("02", "bold"))
        e["run"] = "05"
        self.assertEqual(bc.build_name(e, s), "sub-01_task-x_run-05_bold")
        self.assertEqual(bc.build_name({"inv": "1", "run": "02", "sub": "05"}, "MP2RAGE"),
                         "sub-05_run-02_inv-1_MP2RAGE")
        self.assertAlmostEqual(bc.parse_time("14:04:28.5425"), 50668.5425)
        self.assertAlmostEqual(bc.parse_time("140428.5"), 50668.5)
        self.assertAlmostEqual(bc.parse_time("11:41:1.870000"), 42061.87)   # dcm2niix 秒不补零
        self.assertIsNone(bc.parse_time("garbage"))


def write_cmrr(d, stem, first_tic, n_vol, n_samp=50):
    d.mkdir(parents=True, exist_ok=True)
    info = ["UUID = x", "NumVolumes = {}".format(n_vol), "NumSlices = 1", "",
            "VOLUME SLICE ACQ_START_TICS ACQ_FINISH_TICS ECHO"]
    for v in range(n_vol):
        t = first_tic + v * 800
        info.append("{} 0 {} {} 0".format(v, t, t + 10))
    (d / (stem + "_Info.log")).write_text("\n".join(info) + "\n")
    for code, step in (("PULS", 2), ("RESP", 8)):
        lines = ["UUID = x", "", "ACQ_TIME_TICS CHANNEL VALUE SIGNAL"]
        t0 = first_tic - 100 * step
        for i in range(n_samp):
            lines.append("{} PULS {}".format(t0 + i * step, 1000 + i))
        (d / (stem + "_{}.log".format(code))).write_text("\n".join(lines) + "\n")


class TestPhysioTimeMatch(unittest.TestCase):
    """等长范式：两个 run 帧数相同，只能靠时间配对（旧版按 NumVolumes 配不了）。"""

    def setUp(self):
        self.fp = FakeProject({"loc": [5, 5]})
        t1, t2 = 36000.0, 36600.0
        self.fp.add("sub-01", "func", "sub-01_task-loc_run-01_bold", 5, 9, "loc", t1)
        self.fp.add("sub-01", "func", "sub-01_task-loc_run-02_bold", 5, 12, "loc", t2)
        (self.fp.code / "participants_mapping.tsv").write_text(
            "participant_id\tdicom_dir\tphysio_mode\tphysio_dir\nsub-01\tS0\tfile\t{}\n".format(self.fp.root / "logs"))
        logs = self.fp.root / "logs"
        write_cmrr(logs, "Physio_A", int(t2 * 400), 5)       # 故意先写 run-02 的
        write_cmrr(logs, "Physio_B", int(t1 * 400), 5)
        write_cmrr(logs, "Physio_C", int((t2 + 300) * 400), 3)   # fmap 的 3-volume 组

    def tearDown(self):
        self.fp.cleanup()

    def test_match_by_time(self):
        spec = bc.load_project(str(self.fp.root))
        row = bc.load_mapping(spec)[0]
        res = P.process_session(spec, row)
        got = sorted((m["bold"], m["recording"]) for m in res["matched"])
        self.assertEqual(got, [("sub-01_task-loc_run-01_bold", "pulse"), ("sub-01_task-loc_run-01_bold", "respiratory"),
                               ("sub-01_task-loc_run-02_bold", "pulse"), ("sub-01_task-loc_run-02_bold", "respiratory")])
        self.assertEqual(len(res["unmatched_logs"]), 1)
        meta = json.loads((self.fp.bids / "sub-01" / "func" /
                           "sub-01_task-loc_run-01_recording-pulse_physio.json").read_text())
        self.assertEqual(meta["SamplingFrequency"], 200.0)
        self.assertEqual(meta["StartTime"], -0.5)
        self.assertEqual(res["bolds_without_physio"], [])


if __name__ == "__main__":
    unittest.main()
