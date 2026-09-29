#!/usr/bin/env python3
"""lint_config.py 与 validate.py 的 IntendedFor / 无 session 布局回归测试。

出处：pitfalls #29（dcm2bids 3.x 静默忽略顶层 intended_for）。
运行：python3 -m unittest discover -s tests
"""
import gzip
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import lint_config as L  # noqa: E402
import validate as V     # noqa: E402

OLD_STYLE = """{
  "descriptions": [
    {"id": "bold", "datatype": "func", "suffix": "bold",
     "criteria": {"SeriesDescription": "run", "ImageType": ["ORIGINAL", "M"]}},
    {"id": "rev", "datatype": "fmap", "suffix": "epi",
     "criteria": {"SeriesDescription": "reverse"},
     "intended_for": ["bold"]}
  ]
}
"""


def nii(path, vols):
    hdr = bytearray(352)
    struct.pack_into("<8h", hdr, 40, 4, 8, 8, 4, vols, 1, 1, 1)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wb") as f:
        f.write(hdr)


def sidecar(path, **kw):
    with open(path, "w") as f:
        json.dump(kw, f)


class TestLint(unittest.TestCase):
    def test_old_key_is_error(self):
        errs, _ = L.lint(json.loads(OLD_STYLE))
        self.assertTrue(any("intended_for" in e for e in errs))

    def test_sidecar_changes_is_clean(self):
        cfg = json.loads(OLD_STYLE)
        cfg["descriptions"][1].pop("intended_for")
        cfg["descriptions"][1]["sidecar_changes"] = {"IntendedFor": ["bold"]}
        self.assertEqual(L.lint(cfg), ([], []))

    def test_unknown_id_and_duplicate_id(self):
        cfg = {"descriptions": [
            {"id": "a", "datatype": "func", "suffix": "bold", "criteria": {}},
            {"id": "a", "datatype": "func", "suffix": "sbref", "criteria": {}},
            {"datatype": "fmap", "suffix": "epi", "criteria": {},
             "sidecar_changes": {"IntendedFor": ["nope"]}}]}
        errs, _ = L.lint(cfg)
        self.assertTrue(any("重复" in e for e in errs))
        self.assertTrue(any("nope" in e for e in errs))

    def test_fmap_without_intendedfor_warns(self):
        cfg = {"descriptions": [{"datatype": "fmap", "suffix": "epi", "criteria": {}}]}
        errs, warns = L.lint(cfg)
        self.assertEqual(errs, [])
        self.assertTrue(warns)

    def test_fix_text_changes_only_that_line(self):
        new, n = L.fix_text(OLD_STYLE)
        self.assertEqual(n, 1)
        old_lines, new_lines = OLD_STYLE.splitlines(), new.splitlines()
        diff = [(a, b) for a, b in zip(old_lines, new_lines) if a != b]
        self.assertEqual(len(old_lines), len(new_lines))
        self.assertEqual(len(diff), 1)                          # 行内数组等其余格式不动
        self.assertIn('"sidecar_changes": {"IntendedFor": ["bold"]}', diff[0][1])
        self.assertEqual(L.lint(json.loads(new))[0], [])

    def test_fix_falls_back_when_sidecar_changes_exists(self):
        cfg_text = ('{"descriptions":[{"id":"b","datatype":"func","suffix":"bold","criteria":{}},'
                    '{"datatype":"fmap","suffix":"epi","criteria":{},'
                    '"sidecar_changes":{"TaskName":"t"},"intended_for":["b"]}]}')
        new, n = L.fix_text(cfg_text)
        self.assertIsNone(new)                                  # 文本替换会产生重复键
        cfg = json.loads(cfg_text)
        self.assertEqual(L.fix_obj(cfg), 1)
        self.assertEqual(cfg["descriptions"][1]["sidecar_changes"],
                         {"TaskName": "t", "IntendedFor": ["b"]})


class TestValidate(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        # 无 session 层的布局（这正是原来 volume 检查扫不到的）
        self.sub = os.path.join(self.d, "sub-01")
        nii(os.path.join(self.sub, "func", "sub-01_task-a_run-01_bold.nii.gz"), 100)
        nii(os.path.join(self.sub, "func", "sub-01_task-a_run-02_bold.nii.gz"), 100)
        os.makedirs(os.path.join(self.sub, "fmap"))

    def tearDown(self):
        shutil.rmtree(self.d)

    def fmap(self, name, **kw):
        sidecar(os.path.join(self.sub, "fmap", name + ".json"), **kw)

    def test_volumes_without_session_layer(self):
        rep = V.validate_volumes(self.d)
        self.assertEqual(len(rep["runs"]), 2)

    def test_missing_intendedfor_flagged(self):
        self.fmap("sub-01_dir-PA_run-01_epi")
        rep = V.check_intendedfor(self.d)
        self.assertEqual([a["problem"] for a in rep["anomalies"]], ["没有 IntendedFor"])

    def test_uri_and_relative_both_resolve(self):
        self.fmap("sub-01_dir-PA_run-01_epi",
                  IntendedFor="bids::sub-01/func/sub-01_task-a_run-01_bold.nii.gz")
        self.fmap("sub-01_dir-PA_run-02_epi",
                  IntendedFor=["func/sub-01_task-a_run-02_bold.nii.gz"])
        self.assertEqual(V.check_intendedfor(self.d)["anomalies"], [])

    def test_dangling_target_flagged(self):
        self.fmap("sub-01_dir-PA_run-01_epi",
                  IntendedFor=["func/sub-01_task-a_run-09_bold.nii.gz"])
        rep = V.check_intendedfor(self.d)
        self.assertEqual(len(rep["anomalies"]), 1)
        self.assertIn("不存在", rep["anomalies"][0]["problem"])


if __name__ == "__main__":
    unittest.main()
