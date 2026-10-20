#!/usr/bin/env python3
"""finalize.py：按协议表分配 run、剔废 run、重复结构像、fmap 配对、可重复执行。

运行：python3 -m unittest discover -s tests
"""
import unittest

from helpers import FakeProject
import bids_common as bc
import finalize as F

H = 3600 * 10   # 10:00:00


def run(fp, sub="sub-01", apply=True):
    spec = bc.load_project(str(fp.root))
    status, plan = F.finalize_session(spec, sub, "", apply=apply, quiet=True)
    return status, plan


class TestMovieSession(unittest.TestCase):
    """变长范式：run 1 先废（15 vol）后重扫；每个 bold 之后跟一个 reverse-PE。"""

    def setUp(self):
        self.fp = FakeProject({"movie": [464, 470, 419]})
        fp, s = self.fp, "sub-01"
        t = H
        # dcm2bids 按时间顺序给同名 series 编 run-01..04（废片占了 run-01）
        fp.add(s, "func", "sub-01_task-movie_run-01_sbref", 1, 8, "movie_run_01_SBRef", t)
        fp.add(s, "func", "sub-01_task-movie_run-01_bold", 15, 9, "movie_run_01", t + 12)
        t += 100
        fp.add(s, "func", "sub-01_task-movie_run-02_sbref", 1, 11, "movie_run_01_SBRef", t)
        fp.add(s, "func", "sub-01_task-movie_run-02_bold", 464, 12, "movie_run_01", t + 12)
        fp.add(s, "fmap", "sub-01_dir-PA_run-01_epi", 3, 14, "reverse_PE_01", t + 12 + 928 + 30,
               IntendedFor="bids::sub-01/func/sub-01_task-movie_run-01_bold.nii.gz")
        t += 1100
        fp.add(s, "func", "sub-01_task-movie_run-03_sbref", 1, 16, "movie_run_02_SBRef", t)
        fp.add(s, "func", "sub-01_task-movie_run-03_bold", 470, 17, "movie_run_02", t + 12)
        fp.add(s, "fmap", "sub-01_dir-PA_run-02_epi", 3, 19, "reverse_PE_02", t + 12 + 940 + 30)
        t += 1100
        fp.add(s, "func", "sub-01_task-movie_run-04_sbref", 1, 21, "movie_run_03_SBRef", t)
        fp.add(s, "func", "sub-01_task-movie_run-04_bold", 419, 22, "movie_run_03", t + 12)
        fp.add(s, "fmap", "sub-01_dir-PA_run-03_epi", 3, 24, "reverse_PE_03", t + 12 + 838 + 30)

    def tearDown(self):
        self.fp.cleanup()

    def test_aborted_dropped_runs_by_protocol_fmap_after(self):
        status, plan = run(self.fp)
        self.assertEqual(status, "ok", plan.issues)
        func = self.fp.files("sub-01", "func")
        self.assertEqual(
            [f for f in func if f.endswith("_bold.nii.gz")],
            ["sub-01_task-movie_run-0{}_bold.nii.gz".format(i) for i in (1, 2, 3)])
        self.assertEqual(len([f for f in func if f.endswith("_sbref.nii.gz")]), 3)
        self.assertEqual(self.fp.meta("sub-01", "func", "sub-01_task-movie_run-01_bold")["SeriesNumber"], 12)
        for i in (1, 2, 3):
            m = self.fp.meta("sub-01", "fmap", "sub-01_dir-PA_run-0{}_epi".format(i))
            self.assertEqual(m["IntendedFor"],
                             ["bids::sub-01/func/sub-01_task-movie_run-0{}_bold.nii.gz".format(i)])
        self.assertEqual(self.fp.meta("sub-01", "func", "sub-01_task-movie_run-02_sbref")["TaskName"], "movie")
        disc = list((self.fp.root / "work" / "discarded" / "sub-01").rglob("*.nii.gz"))
        self.assertEqual(sorted(p.name for p in disc),
                         ["sub-01_task-movie_run-01_bold.nii.gz", "sub-01_task-movie_run-01_sbref.nii.gz"])

    def test_idempotent(self):
        run(self.fp)
        status, plan = run(self.fp)
        self.assertEqual(status, "ok")
        self.assertFalse(plan.discard or plan.rename or plan.updates)

    def test_relative_style(self):
        cfg = self.fp.code / "dcm2bids_config.json"
        cfg.write_text('{"bids_uri": "relative", "descriptions": []}')
        run(self.fp)
        m = self.fp.meta("sub-01", "fmap", "sub-01_dir-PA_run-02_epi")
        self.assertEqual(m["IntendedFor"], ["func/sub-01_task-movie_run-02_bold.nii.gz"])

    def test_unmatched_ask_blocks_everything(self):
        p = self.fp.code / "project.json"
        p.write_text(p.read_text().replace('"discard"', '"ask"'))
        before = self.fp.files("sub-01", "func")
        status, plan = run(self.fp)
        self.assertEqual(status, "needs_decision")
        self.assertTrue(any("对不上" in i for i in plan.issues))
        self.assertEqual(self.fp.files("sub-01", "func"), before)

    def test_discard_decision_typo_is_issue(self):
        self.fp.set_decisions([("sub-01", "", "discard", "sn=999", "", "typo")])
        status, plan = run(self.fp)
        self.assertEqual(status, "needs_decision")


class TestPartialSessions(unittest.TestCase):
    def tearDown(self):
        self.fp.cleanup()

    def test_missing_middle_run_keeps_protocol_position(self):
        self.fp = FakeProject({"movie": [464, 470, 419, 467]})
        fp, s = self.fp, "sub-01"
        fp.add(s, "func", "sub-01_task-movie_run-01_bold", 464, 9, "r1", H)
        fp.add(s, "func", "sub-01_task-movie_run-02_bold", 419, 15, "r3", H + 2000)
        fp.add(s, "func", "sub-01_task-movie_run-03_bold", 467, 21, "r4", H + 4000)
        status, plan = run(fp)
        self.assertEqual(status, "ok", plan.issues)
        self.assertEqual([f for f in fp.files(s, "func") if f.endswith(".nii.gz")],
                         ["sub-01_task-movie_run-01_bold.nii.gz", "sub-01_task-movie_run-03_bold.nii.gz",
                          "sub-01_task-movie_run-04_bold.nii.gz"])
        self.assertTrue(any("缺 run [2]" in w for w in plan.warns))

    def test_single_bold_gets_run_entity_and_fmap_follows(self):
        self.fp = FakeProject({"movie": [464, 470]})
        fp, s = self.fp, "sub-01"
        fp.add(s, "func", "sub-01_task-movie_bold", 464, 9, "r1", H)
        fp.add(s, "fmap", "sub-01_dir-PA_epi", 3, 13, "rev1", H + 960)
        status, plan = run(fp)
        self.assertEqual(status, "ok", plan.issues)
        self.assertIn("sub-01_task-movie_run-01_bold.nii.gz", fp.files(s, "func"))
        self.assertIn("sub-01_dir-PA_run-01_epi.json", fp.files(s, "fmap"))

    def test_single_run_task_has_no_run_entity(self):
        self.fp = FakeProject({"rest": [300]})
        fp, s = self.fp, "sub-01"
        fp.add(s, "func", "sub-01_task-rest_bold", 300, 9, "rest", H)
        status, plan = run(fp)
        self.assertEqual(status, "ok", plan.issues)
        self.assertEqual(fp.files(s, "func"), ["sub-01_task-rest_bold.json", "sub-01_task-rest_bold.nii.gz"])

    def test_equal_length_extra_full_run_is_ambiguous(self):
        self.fp = FakeProject({"loc": [170, 170]})
        fp, s = self.fp, "sub-01"
        for i in range(3):
            fp.add(s, "func", "sub-01_task-loc_run-0{}_bold".format(i + 1), 170, 9 + i, "loc", H + i * 400)
        status, plan = run(fp)
        self.assertEqual(status, "needs_decision")
        self.assertTrue(any("不止一种" in i for i in plan.issues))
        fp.set_decisions([("sub-01", "", "discard", "sn=10", "", "被试第 2 遍动得厉害，重扫")])
        status, plan = run(fp)
        self.assertEqual(status, "ok", plan.issues)
        self.assertEqual(fp.meta(s, "func", "sub-01_task-loc_run-02_bold")["SeriesNumber"], 11)

    def test_volume_override(self):
        self.fp = FakeProject({"movie": [464, 470]}, project={"unmatched_func": "ask"})
        fp, s = self.fp, "sub-01"
        fp.add(s, "func", "sub-01_task-movie_run-01_bold", 470, 9, "r", H)
        fp.add(s, "func", "sub-01_task-movie_run-02_bold", 470, 12, "r", H + 1200)
        self.assertEqual(run(fp, apply=False)[0], "needs_decision")
        fp.set_decisions([("sub-01", "", "volumes", "run=1", "470", "现场记录 run-01 实际 470 TR")])
        status, plan = run(fp)
        self.assertEqual(status, "ok", plan.issues)


class TestAnatAndFmap(unittest.TestCase):
    def setUp(self):
        self.fp = FakeProject({"movie": [100]}, project={"unpaired_fmap": "ask"})
        fp, s = self.fp, "sub-01"
        fp.add(s, "anat", "sub-01_run-01_UNIT1", 1, 7, "uni", H)
        fp.add(s, "anat", "sub-01_run-01_inv-1_MP2RAGE", 1, 5, "inv1", H)
        fp.add(s, "anat", "sub-01_run-02_UNIT1", 1, 11, "uni", H + 700)
        fp.add(s, "anat", "sub-01_run-02_inv-1_MP2RAGE", 1, 9, "inv1", H + 700)
        fp.add(s, "func", "sub-01_task-movie_bold", 100, 13, "movie", H + 1500)
        fp.add(s, "fmap", "sub-01_dir-PA_run-01_epi", 3, 15, "rev", H + 1800)
        fp.add(s, "fmap", "sub-01_dir-PA_run-02_epi", 3, 17, "rev", H + 1900)

    def tearDown(self):
        self.fp.cleanup()

    def test_anat_duplicates_ask(self):
        status, plan = run(self.fp)
        self.assertEqual(status, "needs_decision")
        self.assertTrue(any("重复结构像" in i for i in plan.issues))

    def test_anat_last_and_extra_fmap(self):
        self.fp.set_decisions([
            ("sub-01", "", "anat_duplicates", "", "last", "第一套头动，现场重扫"),
            ("sub-01", "", "discard", "sn=17", "", "reverse 扫了两遍，留第一遍")])
        status, plan = run(self.fp)
        self.assertEqual(status, "ok", plan.issues)
        self.assertEqual(self.fp.files("sub-01", "anat"),
                         ["sub-01_UNIT1.json", "sub-01_UNIT1.nii.gz",
                          "sub-01_inv-1_MP2RAGE.json", "sub-01_inv-1_MP2RAGE.nii.gz"])
        self.assertEqual(self.fp.meta("sub-01", "anat", "sub-01_UNIT1")["SeriesNumber"], 11)
        self.assertEqual(self.fp.files("sub-01", "fmap"), ["sub-01_dir-PA_epi.json", "sub-01_dir-PA_epi.nii.gz"])

    def test_unpaired_fmap_is_issue(self):
        self.fp.set_decisions([("sub-01", "", "anat_duplicates", "", "all", "两套都留")])
        status, plan = run(self.fp)
        self.assertEqual(status, "needs_decision")
        self.assertTrue(any("配不上" in i for i in plan.issues))


class TestPairCheck(unittest.TestCase):
    """配对体检：默认规则配上的 reverse 不在同一次匀场 / 同一扫描框下时报警并给候选。"""

    def setUp(self):
        self.fp = FakeProject({"movie": [100, 120]}, project={"unpaired_fmap": "ask"})
        fp, s = self.fp, "sub-01"
        shim_a, shim_b = [1, 2, 3], [9, 2, 3]
        c0 = (0.0, 0.0, 0.0)
        # run-01 在匀场 A 下；它后面的 reverse_PE_01 却是机器重启重新匀场后（B）扫的
        fp.add(s, "func", "sub-01_task-movie_run-01_bold", 100, 9, "r1", H, center=c0, ShimSetting=shim_a)
        fp.add(s, "fmap", "sub-01_dir-PA_run-01_epi", 3, 12, "rev1", H + 260, center=c0, ShimSetting=shim_b)
        fp.add(s, "fmap", "sub-01_dir-PA_run-02_epi", 3, 13, "rev1b", H + 280, center=c0, ShimSetting=shim_a)
        fp.add(s, "func", "sub-01_task-movie_run-02_bold", 120, 15, "r2", H + 400, center=(0.0, 4.0, 0.0),
               ShimSetting=shim_a)
        fp.add(s, "fmap", "sub-01_dir-PA_run-03_epi", 3, 18, "rev2", H + 700, center=c0, ShimSetting=shim_a)

    def tearDown(self):
        self.fp.cleanup()

    def test_warns_with_candidates_but_does_not_switch(self):
        self.fp.set_decisions([("sub-01", "", "discard", "sn=13", "", "测试：先去掉多扫的那张")])
        status, plan = run(self.fp, apply=False)
        self.assertEqual(status, "ok", plan.issues)
        checks = [w for w in plan.warns if w.startswith("[配对体检]")]
        self.assertEqual(len(checks), 2)
        self.assertIn("匀场", checks[0])
        self.assertIn("扫描框不同", checks[1])
        self.assertIn("4.0 mm", checks[1])
        self.assertIn("没有同场同框的候选", checks[1])

    def test_suggested_pair_line_resolves_it(self):
        self.fp.set_decisions([("sub-01", "", "discard", "sn=18", "", "run-02 的 reverse 不在同一扫描框")])
        status, plan = run(self.fp, apply=False)
        w = [x for x in plan.warns if x.startswith("[配对体检]") and "run-01_bold" in x][0]
        self.assertIn("pair\tsn=13\tsn=9", w)
        self.fp.set_decisions([("sub-01", "", "discard", "sn=18", "", "x"),
                               ("sub-01", "", "pair", "sn=13", "sn=9", "reverse_PE_01 重新匀过场，改用同场的那张")])
        status, plan = run(self.fp, apply=False)
        self.assertFalse([x for x in plan.warns if x.startswith("[配对体检]") and "run-01_bold" in x])
        self.assertEqual(status, "needs_decision")                      # 原来那张变成无配对，按 ask 停下
        self.assertTrue(any("配不上" in i and "SN12" in i for i in plan.issues))

    def test_preview_placeholders_without_sform_skip_geometry(self):
        import bids_common as bc2
        from helpers import nii
        p = self.fp.root / "x.nii.gz"
        nii(p, 5)
        self.assertIsNone(bc2.nifti_geometry(p))
        nii(p, 5, center=(1.0, 2.0, 3.0))
        c, n = bc2.nifti_geometry(p)
        self.assertEqual([round(x, 3) for x in c], [1.0, 2.0, 3.0])
        self.assertEqual([round(x, 3) for x in n], [0.0, 0.0, 1.0])


class TestPairingEdgeCases(unittest.TestCase):
    def tearDown(self):
        self.fp.cleanup()

    def test_nearest_with_equal_distance_does_not_crash(self):
        self.fp = FakeProject({"movie": [100]}, project={"fmap_pairing": "nearest"})
        fp, s = self.fp, "sub-01"
        fp.add(s, "fmap", "sub-01_dir-PA_run-01_epi", 3, 5, "rev", H - 50)
        fp.add(s, "fmap", "sub-01_dir-PA_run-02_epi", 3, 6, "rev", H - 50)   # 与上一张同一时刻
        fp.add(s, "func", "sub-01_task-movie_bold", 100, 9, "r", H)
        fp.set_decisions([("sub-01", "", "unpaired_fmap", "", "keep", "测试")])
        status, plan = run(fp, apply=False)
        self.assertEqual(status, "ok", plan.issues)

    def test_none_with_single_explicit_pair(self):
        self.fp = FakeProject({"movie": [100, 120]}, project={"fmap_pairing": "none", "unpaired_fmap": "ask"})
        fp, s = self.fp, "sub-01"
        fp.add(s, "func", "sub-01_task-movie_run-01_bold", 100, 9, "r1", H)
        fp.add(s, "fmap", "sub-01_dir-PA_run-01_epi", 3, 12, "rev1", H + 260)
        fp.add(s, "func", "sub-01_task-movie_run-02_bold", 120, 15, "r2", H + 400)
        fp.add(s, "fmap", "sub-01_dir-PA_run-02_epi", 3, 18, "rev2", H + 700)
        fp.set_decisions([("sub-01", "", "pair", "sn=18", "sn=15", "只给 run-02 做畸变校正")])
        status, plan = run(fp)
        self.assertEqual(status, "ok", plan.issues)
        self.assertNotIn("IntendedFor", fp.meta(s, "fmap", "sub-01_dir-PA_run-01_epi"))
        self.assertEqual(fp.meta(s, "fmap", "sub-01_dir-PA_run-02_epi")["IntendedFor"],
                         ["bids::sub-01/func/sub-01_task-movie_run-02_bold.nii.gz"])

    def test_bad_decision_value_is_readable_error(self):
        self.fp = FakeProject({"movie": [100]})
        self.fp.add("sub-01", "func", "sub-01_task-movie_bold", 100, 9, "r", H)
        self.fp.set_decisions([("sub-01", "", "volumes", "run=1", "四百七十", "x")])
        with self.assertRaises(bc.SpecError):
            run(self.fp, apply=False)


class TestAlign(unittest.TestCase):
    def test_unique_and_ambiguous(self):
        ok = lambda b, r: b == r  # noqa: E731
        n, sols = F.align([464, 15, 470], [464, 470], ok)
        self.assertEqual((n, len(sols)), (2, 1))
        n, sols = F.align([170, 170, 170], [170, 170], ok)
        self.assertEqual(len(sols), 2)


if __name__ == "__main__":
    unittest.main()
