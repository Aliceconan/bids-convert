#!/usr/bin/env python3
"""lint_config.py 与 validate.py 的回归测试。

出处：pitfalls #29（顶层 intended_for 被静默忽略）、#14（写死 task- 时没有 TaskName）。
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
  "case_sensitive": false,
  "bids_uri": "URI",
  "descriptions": [
    {"id": "bold", "datatype": "func", "suffix": "bold", "custom_entities": "task-a",
     "criteria": {"SeriesDescription": "run", "ImageType": ["ORIGINAL", "M"]},
     "sidecar_changes": {"TaskName": "a"}},
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
            {"id": "a", "datatype": "anat", "suffix": "T1w", "criteria": {}},
            {"id": "a", "datatype": "anat", "suffix": "T2w", "criteria": {}},
            {"datatype": "fmap", "suffix": "epi", "criteria": {},
             "sidecar_changes": {"IntendedFor": ["nope"]}}]}
        errs, _ = L.lint(cfg)
        self.assertTrue(any("重复" in e for e in errs))
        self.assertTrue(any("nope" in e for e in errs))

    def test_fmap_without_intendedfor_warns(self):
        cfg = {"bids_uri": "URI", "case_sensitive": False,
               "descriptions": [{"datatype": "fmap", "suffix": "epi", "criteria": {}}]}
        errs, warns = L.lint(cfg)
        self.assertEqual(errs, [])
        self.assertTrue(any("IntendedFor" in w for w in warns))

    def test_taskname_required_and_fixable(self):
        cfg = {"descriptions": [{"id": "b", "datatype": "func", "suffix": "bold",
                                 "custom_entities": "task-movie", "criteria": {}}]}
        errs, warns = L.lint(cfg)
        self.assertTrue(any("TaskName" in e for e in errs))
        self.assertTrue(any("bids_uri" in w for w in warns))
        self.assertTrue(any("case_sensitive" in w for w in warns))
        L.fix_obj(cfg)
        L.fix_top(cfg)
        self.assertEqual(cfg["descriptions"][0]["sidecar_changes"]["TaskName"], "movie")
        self.assertEqual(L.lint(cfg), ([], []))

    def test_bad_top_level_values(self):
        errs, warns = L.lint({"bids_uri": "uri", "case_sensitive": "false", "foo": 1, "descriptions": []})
        self.assertEqual(len(errs), 2)
        self.assertTrue(any("foo" in w for w in warns))

    def test_re_mode_prefix_warning(self):
        cfg = {"search_method": "re", "bids_uri": "URI",
               "descriptions": [{"datatype": "anat", "suffix": "T1w",
                                 "criteria": {"SeriesDescription": "mprage"}}]}
        _, warns = L.lint(cfg)
        self.assertTrue(any("$" in w for w in warns))

    def test_fix_text_changes_only_that_line(self):
        new, n = L.fix_text(OLD_STYLE)
        self.assertEqual(n, 1)
        old_lines, new_lines = OLD_STYLE.splitlines(), new.splitlines()
        diff = [(a, b) for a, b in zip(old_lines, new_lines) if a != b]
        self.assertEqual(len(old_lines), len(new_lines))
        self.assertEqual(len(diff), 1)                          # 行内数组等其余格式不动
        self.assertIn('"sidecar_changes": {"IntendedFor": ["bold"]}', diff[0][1])
        self.assertEqual(L.lint(json.loads(new))[0], [])

    def test_fix_never_double_wraps_correct_config(self):
        good = ('{"descriptions":[{"id":"b","datatype":"anat","suffix":"T1w","criteria":{}},'
                '{"datatype":"fmap","suffix":"epi","criteria":{},"sidecar_changes":{"IntendedFor":["b"]}}]}')
        self.assertEqual(L.fix_text(good), (good, 0))
        mixed = ('{"descriptions":[{"id":"b","datatype":"anat","suffix":"T1w","criteria":{}},'
                 '{"datatype":"fmap","suffix":"epi","criteria":{},"sidecar_changes":{"IntendedFor":["b"]}},'
                 '{"datatype":"fmap","suffix":"epi","criteria":{},"intended_for":["b"]}]}')
        self.assertEqual(L.fix_text(mixed), (None, 0))          # 退回结构化改写
        cfg = json.loads(mixed)
        L.fix_obj(cfg)
        self.assertEqual([d.get("sidecar_changes") for d in cfg["descriptions"][1:]],
                         [{"IntendedFor": ["b"]}, {"IntendedFor": ["b"]}])

    def test_fix_falls_back_when_sidecar_changes_exists(self):
        cfg_text = ('{"descriptions":[{"id":"b","datatype":"anat","suffix":"T1w","criteria":{}},'
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
        rep = V.check_intendedfor(self.d)
        self.assertTrue(all(f["missing_targets"] == [] for f in rep["fmaps"]))   # 两种写法都能解析
        self.assertEqual(len(rep["targeted"]), 2)

    def test_mixed_styles_flagged(self):
        self.fmap("sub-01_dir-PA_run-01_epi",
                  IntendedFor=["bids::sub-01/func/sub-01_task-a_run-01_bold.nii.gz"])
        self.fmap("sub-01_dir-PA_run-02_epi",
                  IntendedFor=["func/sub-01_task-a_run-02_bold.nii.gz"])
        rep = V.check_intendedfor(self.d)
        self.assertTrue(any("混用" in a["problem"] for a in rep["anomalies"]))

    def test_style_must_match_config(self):
        self.fmap("sub-01_dir-PA_run-01_epi", IntendedFor=["func/sub-01_task-a_run-01_bold.nii.gz"])
        rep = V.check_intendedfor(self.d, style="URI")
        self.assertEqual(len(rep["anomalies"]), 1)

    def test_volumes_against_protocol(self):
        rep = V.validate_volumes(self.d, {"a": {1: (100, 0), 2: (90, 0), 3: (50, 0)}})
        self.assertEqual([a["file"] for a in rep["anomalies"]], ["sub-01_task-a_run-02_bold.nii.gz"])
        self.assertTrue(any("缺 run [3]" in w for w in rep["warnings"]))

    def test_volumes_without_protocol_never_flags(self):
        nii(os.path.join(self.sub, "func", "sub-01_task-a_run-03_bold.nii.gz"), 20)
        self.assertEqual(V.validate_volumes(self.d)["anomalies"], [])

    def test_taskname_missing_and_inherited(self):
        sidecar(os.path.join(self.sub, "func", "sub-01_task-a_run-01_bold.json"))
        sidecar(os.path.join(self.sub, "func", "sub-01_task-a_run-02_bold.json"), TaskName="a")
        self.assertEqual(len(V.check_taskname(self.d)["anomalies"]), 1)
        sidecar(os.path.join(self.d, "task-a_bold.json"), TaskName="a")
        self.assertEqual(V.check_taskname(self.d)["anomalies"], [])

    def test_dangling_target_flagged(self):
        self.fmap("sub-01_dir-PA_run-01_epi",
                  IntendedFor=["func/sub-01_task-a_run-09_bold.nii.gz"])
        rep = V.check_intendedfor(self.d)
        self.assertEqual(len(rep["anomalies"]), 1)
        self.assertIn("不存在", rep["anomalies"][0]["problem"])


if __name__ == "__main__":
    unittest.main()
