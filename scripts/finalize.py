#!/usr/bin/env python3
"""finalize.py — dcm2bids 产出之后、按项目声明把一个 session 收拾成最终 BIDS。

为什么需要这一步：dcm2bids 只做「series → 文件名」的匹配，下面这些它做不了或做错：

  * run 编号：它只在同名冲突时按顺序编 run-01/02…，单个 run 不加 run 实体；
    废 run 也占号。本脚本按 protocol.tsv 给每个 bold 分配**协议里的位置**
    （run-04 永远是第 4 段，缺扫允许缺号）。
  * 废 run / 重复结构像 / 测试序列：按 decisions.tsv 和 project.json 的策略处理，
    剔除的文件**移到 work/discarded/，不删除**。
  * fmap 的 IntendedFor：dcm2bids 的 ["bold"] 是按处理顺序累积的（第 k 个 fmap
    指向此前所有 bold），且引用的是改名前的文件。本脚本按声明的配对规则
    （after/before/nearest/index/all）用采集时间重新配对，写法跟随 config 的 bids_uri。
  * TaskName：保证每个 func sidecar 都有。

安全约定：
  * 先完整算出计划；只要有一处无法自动决定（多出来的 bold、没说留哪套的重复结构像、
    配不上的 fmap……），**整体停下、不动任何文件**，列出需要人决定的事项。
  * 可重复执行：对已收拾过的 session 再跑一遍，计划为空。
  * 默认 dry-run，加 --apply 才执行。

用法：
  python3 finalize.py <project_dir> --only sub-01            # dry-run
  python3 finalize.py <project_dir> --only sub-01 --apply
  python3 finalize.py <project_dir> --apply                  # mapping 里全部 session
  python3 finalize.py <project_dir> --bids-dir <其他目录> ...  # 对预演目录跑（preview.py 用）
退出码：0 正常；2 有待人工决定的事项（未改动任何文件）；1 声明文件错误
"""
import argparse
import fnmatch
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bids_common as bc  # noqa: E402

COMPANION_MAX_DT = 300.0      # sbref/phase 等与所属 bold 的最大采集时间差（秒）

# 配对体检阈值：fmap 与所配 bold 是否在同一次匀场 / 同一发射校准 / 同一扫描框下
FREQ_TOL_MHZ = 1e-5           # 中心频率差 > 10 Hz 视为重新调过频
TXREF_TOL = 0.01              # 发射参考幅度相对差 > 1%
CENTER_TOL_MM = 1.0           # 扫描框中心距离
ANGLE_TOL_DEG = 1.0           # 层面法向夹角


# ---------------------------------------------------------------- 选择器

def parse_selector(text):
    """'sn=5,6,7' / 'sd=*TEST*' / 'time=13:41:07' / 'run=3' / 'task=coco'，可用 & 组合。"""
    conds = []
    for part in [p for p in text.split("&") if p.strip()]:
        if "=" not in part:
            raise bc.SpecError("选择器 {!r} 写错（应为 key=value）".format(text))
        k, v = [x.strip() for x in part.split("=", 1)]
        k = k.lower()
        if k == "sn":
            try:
                conds.append(("sn", {int(x) for x in v.split(",") if x.strip()}))
            except ValueError:
                raise bc.SpecError("选择器 {!r}: sn 只能是整数列表".format(text))
        elif k == "sd":
            conds.append(("sd", v.lower()))
        elif k == "time":
            t = bc.parse_time(v if v.count(":") == 2 else v + ":00")
            if t is None:
                raise bc.SpecError("选择器 {!r}: time 应为 HH:MM[:SS]".format(text))
            conds.append(("time", (t, v.count(":") == 2)))
        elif k in ("run", "task", "datatype", "suffix"):
            conds.append((k, v))
        else:
            raise bc.SpecError("选择器 {!r}: 不认识 {}（可用 sn/sd/time/run/task/datatype/suffix）".format(text, k))
    if not conds:
        raise bc.SpecError("选择器为空")
    return conds


def sel_match(conds, im):
    for k, v in conds:
        if k == "sn" and im.sn not in v:
            return False
        if k == "sd" and not fnmatch.fnmatchcase(im.sd.lower(), v):
            return False
        if k == "time":
            t, has_sec = v
            if im.time is None or abs(im.time - t) > (1.0 if has_sec else 60.0):
                return False
        if k == "run" and int(im.ents.get("run", "0") or 0) != int(v):
            return False
        if k == "task" and im.ents.get("task") != v:
            return False
        if k == "datatype" and im.datatype != v:
            return False
        if k == "suffix" and im.suffix != v:
            return False
    return True


# ---------------------------------------------------------------- 协议匹配

def align(bolds, runs, ok):
    """bold（按时间）与协议 run（按顺序）的单调最大匹配。

    返回 (匹配数, 最优解列表[最多 2 个])；每个解是 ((bold_idx, run), ...)。
    有两个及以上最优解说明数据本身有歧义（比如多出一个完整长度的 bold），交给人决定。
    """
    n, m = len(bolds), len(runs)
    memo = {}

    def solve(i, j):
        if i >= n or j >= m:
            return 0, [()]
        key = (i, j)
        if key in memo:
            return memo[key]
        cands = []
        b1, s1 = solve(i + 1, j)
        cands.append((b1, s1))
        b2, s2 = solve(i, j + 1)
        cands.append((b2, s2))
        if ok(bolds[i], runs[j]):
            b3, s3 = solve(i + 1, j + 1)
            cands.append((b3 + 1, [((i, runs[j]),) + s for s in s3]))
        best = max(c[0] for c in cands)
        sols = []
        for b, ss in cands:
            if b == best:
                for s in ss:
                    if s not in sols:
                        sols.append(s)
        memo[key] = (best, sols[:2])
        return memo[key]

    return solve(0, 0)


# ---------------------------------------------------------------- 计划

class Plan(object):
    def __init__(self, spec, sub, ses, sess_dir, bids_dir):
        self.spec, self.sub, self.ses = spec, sub, ses
        self.sess_dir, self.bids_dir = Path(sess_dir), Path(bids_dir)
        self.prefix = bc.prefix_of(sub, ses)
        self.discard = {}        # Image -> 原因
        self.rename = {}         # Image -> 新 stem 名（不含扩展名）
        self.updates = {}        # Image -> {json 键: 值}（值为 None 表示删除该键）
        self.issues = []         # 需要人决定的事项；非空则不执行
        self.warns = []
        self.notes = []          # 决策命中情况等说明

    def final_name(self, im):
        return self.rename.get(im, im.stem.name)

    def final_img(self, im):
        return im.img.parent / (self.final_name(im) + im.ext)

    def set_ents(self, im, ents):
        new = bc.build_name(ents, im.suffix)
        if new != im.stem.name:
            self.rename[im] = new
        else:
            self.rename.pop(im, None)


def bold_key(im):
    return im.stem.name[: -len("_" + im.suffix)]


def build_plan(spec, sub, ses, bids_dir=None):
    bids_dir = Path(bids_dir) if bids_dir else Path(spec["bids_dir"])
    sess_dir = bids_dir / sub / ses if ses else bids_dir / sub
    plan = Plan(spec, sub, ses, sess_dir, bids_dir)
    if not sess_dir.is_dir():
        plan.issues.append("session 目录不存在：{}（dcm2bids 没有产出？）".format(sess_dir))
        return plan

    cfg = bc.load_config(spec)
    style = cfg.get("bids_uri", "URI")
    protocol = bc.load_protocol(spec)
    decisions = bc.load_decisions(spec, sub, ses)
    images = bc.session_images(sess_dir)

    # ---- 决策：session 级覆盖
    policy = {k: spec[k] for k in ("anat_duplicates", "fmap_pairing", "unmatched_func", "unpaired_fmap")}
    vol_override, forced, pairs = {}, [], []
    for d in decisions:
        act = d.get("action", "").lower()
        tgt, val, why = d.get("target", ""), d.get("value", ""), d.get("reason", "")
        if not why:
            plan.warns.append("decisions.tsv 有一行没写 reason：{} {} {}".format(act, tgt, val))
        if act == "discard":
            conds = parse_selector(tgt)
            hit = [im for im in images if sel_match(conds, im)]
            if not hit:
                plan.issues.append("decisions: discard {!r} 一个文件都没匹配到（拼错了？）".format(tgt))
            for im in hit:
                plan.discard[im] = "decisions: " + (why or "discard " + tgt)
        elif act in ("anat_duplicates", "fmap_pairing", "unmatched_func", "unpaired_fmap"):
            allowed = bc.CHOICES[act]
            if val not in allowed:
                raise bc.SpecError("decisions: {} = {!r}，只能是 {}".format(act, val, "/".join(allowed)))
            policy[act] = val
        elif act == "volumes":
            conds = dict((k, v) for k, v in parse_selector(tgt))
            if "run" not in conds or not val.isdigit() or not str(conds["run"]).isdigit():
                raise bc.SpecError("decisions: volumes 写法是 target=run=N（可加 &task=X），value=帧数；"
                                   "现在是 {!r} / {!r}".format(tgt, val))
            vol_override[(conds.get("task"), int(conds["run"]))] = int(val)
        elif act == "assign":
            rv = val.split("=", 1)[-1].strip()
            if not rv.isdigit():
                raise bc.SpecError("decisions: assign 的 value 写 run=N 或 N，现在是 {!r}".format(val))
            run = int(rv)
            conds = parse_selector(tgt)
            hit = [im for im in images if im.suffix == "bold" and sel_match(conds, im)]
            if len(hit) != 1:
                plan.issues.append("decisions: assign {!r} 应恰好匹配 1 个 bold，实际 {} 个".format(tgt, len(hit)))
            else:
                forced.append((hit[0], run))
        elif act == "pair":
            fc, bcnd = parse_selector(tgt), parse_selector(val)
            fm = [im for im in images if im.datatype == "fmap" and sel_match(fc, im)]
            bo = [im for im in images if im.suffix == "bold" and sel_match(bcnd, im)]
            if not fm or not bo:
                plan.issues.append("decisions: pair {!r} → {!r} 没匹配到 fmap 或 bold".format(tgt, val))
            for f in fm:
                pairs.append((f, bo))
        elif act == "note" or not act:
            continue
        else:
            raise bc.SpecError("decisions: 不认识的 action {!r}（discard/assign/volumes/pair/"
                               "anat_duplicates/fmap_pairing/unmatched_func/unpaired_fmap/note）".format(act))

    alive = lambda im: im not in plan.discard  # noqa: E731

    plan_anat(plan, [im for im in images if im.datatype == "anat" and alive(im)], policy)
    kept_bolds = plan_func(plan, images, protocol, policy, vol_override, forced)
    plan_fmap(plan, [im for im in images if im.datatype == "fmap" and alive(im)],
              kept_bolds, policy, pairs, style)
    plan_taskname(plan, [im for im in images if im.datatype == "func" and alive(im)])

    # ---- 最终文件名不能撞
    finals = {}
    for im in images:
        if im in plan.discard:
            continue
        p = plan.final_img(im)
        if p in finals:
            plan.issues.append("改名后撞名：{} 与 {} 都会变成 {}".format(
                im.stem.name, finals[p].stem.name, p.name))
        finals[p] = im
    return plan


def plan_anat(plan, anats, policy):
    groups = {}
    for im in anats:
        key = (im.suffix, tuple(sorted((k, v) for k, v in im.ents.items() if k not in ("run", "_extra"))))
        groups.setdefault(key, []).append(im)
    for key, ims in groups.items():
        ims.sort(key=bc.Image.sort_key)
        if len(ims) > 1:
            how = policy["anat_duplicates"]
            if how == "ask":
                plan.issues.append(
                    "重复结构像 {}：{} 个 —— 在 decisions.tsv 写 anat_duplicates first/last/all，"
                    "或 discard sn=…\n      ".format(key[0], len(ims)) +
                    "\n      ".join(im.label() for im in ims))
                continue
            if how in ("first", "last"):
                keep = ims[0] if how == "first" else ims[-1]
                for im in ims:
                    if im is not keep:
                        plan.discard[im] = "anat_duplicates={}".format(how)
                ims = [keep]
            else:
                for i, im in enumerate(ims, 1):
                    e = dict(im.ents)
                    e["run"] = "{:02d}".format(i)
                    plan.set_ents(im, e)
                continue
        im = ims[0]
        e = dict(im.ents)
        e.pop("run", None)
        plan.set_ents(im, e)


def plan_func(plan, images, protocol, policy, vol_override, forced):
    funcs = [im for im in images if im.datatype == "func"]
    bolds = [im for im in funcs if im.suffix == "bold"]
    kept = []
    forced_map = dict((b, r) for b, r in forced)
    for task in sorted({b.ents.get("task", "") for b in bolds}):
        tb = [b for b in bolds if b.ents.get("task", "") == task]
        if not task:
            plan.issues.append("bold 没有 task 实体：{}".format([b.stem.name for b in tb]))
            continue
        if task not in protocol:
            plan.issues.append("protocol.tsv 里没有 task-{}（{} 个 bold 无从核对）".format(task, len(tb)))
            continue
        runs = protocol[task]
        multi = len(runs) > 1

        def expect(r):
            vol, tol = runs[r]
            return vol_override.get((task, r), vol_override.get((None, r), vol)), tol

        assigned = {}
        for b in tb:
            if b in forced_map and b not in plan.discard:
                r = forced_map[b]
                if r not in runs:
                    plan.issues.append("decisions: assign 到 task-{} 不存在的 run {}".format(task, r))
                    continue
                assigned[b] = r
        free = [b for b in tb if b not in plan.discard and b not in assigned]
        free_runs = [r for r in sorted(runs) if r not in assigned.values()]

        def ok(b, r):
            vol, tol = expect(r)
            return abs(b.volumes - vol) <= tol

        n, sols = align(free, free_runs, ok)
        if len(sols) > 1:
            a, b2 = [dict(s) for s in sols[:2]]
            diff = sorted(set(a.items()) ^ set(b2.items()))
            plan.issues.append(
                "task-{} 的 bold 与协议表有不止一种对应方式，需要人定（decisions: assign 或 discard）：\n      ".format(task) +
                "\n      ".join("{}  {} vol → 可能是 run {}".format(free[i].label(), free[i].volumes, r)
                               for i, r in diff))
            continue
        for i, r in sols[0]:
            assigned[free[i]] = r
        for b in free:
            if b not in assigned:
                if policy["unmatched_func"] == "discard":
                    plan.discard[b] = "与协议表任何 run 都对不上（{} vol）".format(b.volumes)
                else:
                    plan.issues.append(
                        "bold 与协议表对不上：{}  {} vol —— 废 run 就 discard；"
                        "确认这类一律丢弃可设 unmatched_func=discard".format(b.label(), b.volumes))
        missing = [r for r in sorted(runs) if r not in assigned.values()]
        if missing:
            plan.warns.append("task-{} 缺 run {}（协议 {} 个，实有 {} 个）".format(
                task, missing, len(runs), len(assigned)))
        for b, r in sorted(assigned.items(), key=lambda kv: kv[1]):
            e = dict(b.ents)
            if multi:
                e["run"] = "{:02d}".format(r)
            else:
                e.pop("run", None)
            plan.set_ents(b, e)
            kept.append(b)

        # sbref / phase 等伴随文件：跟着时间上最近的 bold 走
        comps = [c for c in funcs if c.suffix != "bold" and c.ents.get("task", "") == task
                 and c not in plan.discard]
        owner_of = {}
        for c in comps:
            cand = [(abs(c.time - b.time), b) for b in tb
                    if c.time is not None and b.time is not None and abs(c.time - b.time) <= COMPANION_MAX_DT]
            cand.sort(key=lambda x: x[0])
            if not cand or (len(cand) > 1 and cand[0][0] == cand[1][0]):
                if policy["unmatched_func"] == "discard":
                    plan.discard[c] = "找不到所属 bold"
                else:
                    plan.issues.append("{} 找不到唯一所属的 bold（时间差 ≤{}s）".format(c.label(), int(COMPANION_MAX_DT)))
                continue
            b = cand[0][1]
            if b in plan.discard or b not in assigned:
                plan.discard[c] = "所属 bold 被剔除（{}）".format(b.stem.name)
                continue
            key = (b, c.suffix, tuple(sorted((k, v) for k, v in c.ents.items() if k not in ("run", "task", "_extra"))))
            if key in owner_of:
                plan.issues.append("{} 与 {} 都归属 {}，需要 discard 一个".format(
                    c.label(), owner_of[key].label(), b.stem.name))
                continue
            owner_of[key] = c
            e = dict(c.ents)
            if multi:
                e["run"] = "{:02d}".format(assigned[b])
            else:
                e.pop("run", None)
            plan.set_ents(c, e)
    return kept


def interval_distance(t, b):
    if b.time is None or t is None:
        return 1e9
    end = b.end_time or b.time
    if t < b.time:
        return b.time - t
    if t > end:
        return t - end
    return 0.0


def pair_problems(f, b):
    """fmap 与 bold 是否在同一次匀场、同一发射校准、同一扫描框下。返回问题列表（空 = 通过）。

    只能看出「重新匀场 / 重新调频 / 发射校准被改 / 重新定位」；被试头动造成的错位要靠 QC 配准。"""
    import math
    out = []
    fm, bm = f.meta, b.meta
    if fm.get("ShimSetting") and bm.get("ShimSetting") and fm["ShimSetting"] != bm["ShimSetting"]:
        diff = max(abs(x - y) for x, y in zip(fm["ShimSetting"], bm["ShimSetting"]))
        out.append("匀场电流不同（最大差 {}）—— 中途重新匀过场，topup 的前提不成立".format(diff))
    ff, bf = fm.get("ImagingFrequency"), bm.get("ImagingFrequency")
    if ff and bf and abs(ff - bf) > FREQ_TOL_MHZ:
        out.append("中心频率差 {:.0f} Hz".format(abs(ff - bf) * 1e6))
    ft, bt = fm.get("TxRefAmp"), bm.get("TxRefAmp")
    if ft and bt and abs(ft - bt) / max(ft, bt) > TXREF_TOL:
        out.append("发射参考幅度 {} vs {}（翻转角约为标称的 {:.0%}）—— 可能被手动改过".format(ft, bt, min(ft, bt) / max(ft, bt)))
    gf, gb = f.geometry, b.geometry
    if gf and gb:
        dist = math.sqrt(sum((x - y) ** 2 for x, y in zip(gf[0], gb[0])))
        cosang = min(1.0, abs(sum(x * y for x, y in zip(gf[1], gb[1]))))
        ang = math.degrees(math.acos(cosang))
        if dist > CENTER_TOL_MM or ang > ANGLE_TOL_DEG:
            out.append("扫描框不同：中心差 {:.1f} mm、法向差 {:.1f}° —— 中途重新定位过".format(dist, ang))
    return out


def check_pairs(plan, pairing, live, fmaps_all, dirkey):
    """每个配对做体检；不通过只报警，并列出能通过体检的候选 fmap 和可照抄的 decisions 行。"""
    for f in live:
        for b in pairing[f]:
            probs = pair_problems(f, b)
            if not probs:
                continue
            cands = [g for g in fmaps_all if g is not f and g not in plan.discard and dirkey(g) == dirkey(f)
                     and not pair_problems(g, b)]
            cands.sort(key=lambda g: interval_distance(g.time, b))      # 时间上越近，B0 漂移越小
            msg = "[配对体检] {} → {}：{}".format(plan.final_name(f), plan.final_name(b), "；".join(probs))
            if cands:
                msg += "\n      同场同框的候选：" + "、".join("{} (SN{})".format(plan.final_name(g), g.sn) for g in cands)
                g = cands[0]
                sns = sorted({x.sn for x in pairing.get(g, [])} | {b.sn})
                msg += ("\n      若改用 {}，decisions.tsv 写：{}\t{}\tpair\tsn={}\tsn={}\t<原因>"
                        "（它原本配的 run 一并保留；{} 随之变成无配对，按 unpaired_fmap 处理）").format(
                    plan.final_name(g), plan.sub, plan.ses, g.sn, ",".join(str(x) for x in sns), plan.final_name(f))
            else:
                msg += "\n      没有同场同框的候选 fmap：考虑该 run 不做畸变校正或排除，结论写进 decision_log"
            plan.warns.append(msg)


def plan_fmap(plan, fmaps, kept_bolds, policy, explicit, style):
    if not fmaps:
        return
    how = policy["fmap_pairing"]
    bolds = sorted(kept_bolds, key=bc.Image.sort_key)
    dirkey = lambda f: (f.ents.get("dir", ""), f.ents.get("acq", ""), f.suffix)  # noqa: E731
    fm = sorted(fmaps, key=bc.Image.sort_key)
    pairing = dict((f, []) for f in fm)

    if how == "after" or how == "before":
        for f in fm:
            if f.time is None:
                continue
            if how == "after":
                cand = [b for b in bolds if b.time is not None and b.time < f.time]
                b = cand[-1] if cand else None
                lo, hi = (b.time if b else None), f.time
            else:
                cand = [b for b in bolds if b.time is not None and b.time > f.time]
                b = cand[0] if cand else None
                lo, hi = f.time, (b.time if b else None)
            if b is None:
                continue
            between = [g for g in fm if g is not f and dirkey(g) == dirkey(f)
                       and g.time is not None and lo < g.time < hi]
            if not between:
                pairing[f] = [b]
    elif how == "nearest":
        for b in bolds:
            for key in sorted({dirkey(f) for f in fm}):
                cand = sorted((f for f in fm if dirkey(f) == key),
                              key=lambda f: (interval_distance(f.time, b),) + f.sort_key())
                if cand:
                    pairing[cand[0]].append(b)
    elif how == "index":
        for key in sorted({dirkey(f) for f in fm}):
            fs = [f for f in fm if dirkey(f) == key]
            for f, b in zip(fs, bolds):
                pairing[f] = [b]
    elif how == "all":
        for f in fm:
            pairing[f] = list(bolds)

    explicit_fm = set()
    for f, bs in explicit:
        if f in pairing:
            pairing[f] = sorted(bs, key=bc.Image.sort_key)
            explicit_fm.add(f)
            plan.notes.append("decisions: {} 显式配对 → {}".format(f.stem.name, [b.stem.name for b in bs]))
    # 显式配对对所涉 bold 独占：同方向的其他 fmap 不再按默认规则指向它
    for f in explicit_fm:
        for g in fm:
            if g not in explicit_fm and dirkey(g) == dirkey(f):
                pairing[g] = [b for b in pairing[g] if b not in pairing[f]]

    if how == "none" and not explicit:
        for f in fm:
            if "IntendedFor" in f.meta:
                plan.updates.setdefault(f, {})["IntendedFor"] = None
        plan.warns.append("fmap_pairing=none：已去掉 dcm2bids 写的 IntendedFor，fmap 不会被用于畸变校正")
        return

    for f in fm:
        if not pairing[f]:
            if how == "none":                 # 只有个别 pair 决策，其余本来就不配
                if "IntendedFor" in f.meta:
                    plan.updates.setdefault(f, {})["IntendedFor"] = None
                continue
            if policy["unpaired_fmap"] == "discard":
                plan.discard[f] = "fmap 没有配对的 bold（fmap_pairing={}）".format(how)
            elif policy["unpaired_fmap"] == "keep":
                plan.warns.append("fmap 没有配对的 bold，保留但无 IntendedFor：{}".format(f.label()))
                plan.updates.setdefault(f, {})["IntendedFor"] = None
            else:
                plan.issues.append("fmap 配不上任何 bold（fmap_pairing={}）：{} —— 多余的就 discard，"
                                   "或设 unpaired_fmap=discard/keep".format(how, f.label()))
    live = [f for f in fm if f not in plan.discard]
    for b in bolds:
        if how != "none" and not any(b in pairing[f] for f in live):
            plan.warns.append("bold 没有配到 fmap：{}".format(plan.final_name(b)))

    # fmap 改名：严格 1:1 时 run 号跟 bold 走，否则按时间顺序编号
    one_to_one = all(len(pairing[f]) == 1 for f in live) and \
        len({(dirkey(f), pairing[f][0]) for f in live}) == len(live)
    for key in sorted({dirkey(f) for f in live}):
        fs = [f for f in live if dirkey(f) == key]
        for i, f in enumerate(fs, 1):
            e = dict(f.ents)
            if one_to_one:
                br = bc.parse_name(plan.final_name(pairing[f][0]))[0].get("run")
                if br:
                    e["run"] = br
                else:
                    e.pop("run", None)
            elif len(fs) > 1:
                e["run"] = "{:02d}".format(i)
            else:
                e.pop("run", None)
            plan.set_ents(f, e)
    check_pairs(plan, pairing, live, fm, dirkey)
    for f in live:
        targets = [bc.intended_for_entry(plan.bids_dir, plan.final_img(b), style) for b in pairing[f]]
        if targets and f.meta.get("IntendedFor") != targets:
            plan.updates.setdefault(f, {})["IntendedFor"] = targets


def plan_taskname(plan, funcs):
    for im in funcs:
        task = im.ents.get("task")
        if not task:
            continue
        cur = im.meta.get("TaskName")
        if cur != task:
            if cur:
                plan.warns.append("{} 的 TaskName={!r} 与文件名 task-{} 不一致，改为后者".format(im.stem.name, cur, task))
            plan.updates.setdefault(im, {})["TaskName"] = task


# ---------------------------------------------------------------- 执行

def sidecar_tables(im):
    """与 bold 同前缀的表格文件（physio / events），改名、剔除时随 bold 一起走。"""
    if im.suffix != "bold":
        return []
    base = bold_key(im) + "_"
    return [p for p in im.img.parent.iterdir() if p.name.startswith(base) and
            any(t in p.name for t in ("_physio.", "_events.", "_stim."))]


def apply_plan(plan):
    spec = plan.spec
    stamp = time.strftime("%Y%m%d-%H%M%S")
    disc_root = Path(spec["work_dir"]) / "discarded" / plan.prefix / stamp
    moved = []
    for im, why in plan.discard.items():
        dest = disc_root / im.datatype
        dest.mkdir(parents=True, exist_ok=True)
        for p in [im.img, im.json] + sidecar_tables(im):
            if p.exists():
                shutil.move(str(p), str(dest / p.name))
                moved.append((str(p), why))
    if moved:
        (disc_root / "REASONS.tsv").write_text(
            "file\treason\n" + "".join("{}\t{}\n".format(Path(p).name, w) for p, w in moved))

    # 两阶段改名，避免链式改名时覆盖还没处理的源文件
    staged = []
    for im, new in plan.rename.items():
        files = [(im.img, new + im.ext), (im.json, new + ".json")]
        old_base, new_base = im.stem.name[: -len(im.suffix)], new[: -len(im.suffix)]
        for t in sidecar_tables(im):
            files.append((t, t.name.replace(old_base, new_base, 1)))
        for src, dst_name in files:
            if src.exists():
                tmp = src.with_name(src.name + ".finalize-tmp")
                src.rename(tmp)
                staged.append((tmp, src.parent / dst_name))
    for tmp, dst in staged:
        if dst.exists():
            raise SystemExit("改名目标已存在（不应发生）：{}".format(dst))
        tmp.rename(dst)

    for im, upd in plan.updates.items():
        j = plan.final_img(im)
        j = Path(bc.split_image(j)[0] + ".json")
        d = json.loads(j.read_text())
        for k, v in upd.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v
        j.write_text(json.dumps(d, indent=4, ensure_ascii=False) + "\n")

    rep_dir = Path(spec["work_dir"]) / "finalize"
    rep_dir.mkdir(parents=True, exist_ok=True)
    (rep_dir / "{}_{}.json".format(plan.prefix, stamp)).write_text(json.dumps({
        "session": plan.prefix,
        "discarded": dict((im.stem.name, w) for im, w in plan.discard.items()),
        "renamed": dict((im.stem.name, n) for im, n in plan.rename.items()),
        "updated": dict((plan.final_name(im), list(u)) for im, u in plan.updates.items()),
        "warnings": plan.warns, "notes": plan.notes,
    }, indent=2, ensure_ascii=False))
    return disc_root if moved else None


def report(plan, applied):
    print("=== {} ===".format(plan.prefix))
    for im, why in sorted(plan.discard.items(), key=lambda kv: kv[0].sort_key()):
        print("  剔除  {}  ← {}".format(im.label(), why))
    for im, new in sorted(plan.rename.items(), key=lambda kv: kv[0].sort_key()):
        print("  改名  {} → {}".format(im.stem.name, new))
    for im, upd in plan.updates.items():
        for k, v in upd.items():
            show = "（删除）" if v is None else (v if not isinstance(v, list) or len(v) > 1 else v[0])
            print("  {:<11} {}: {}".format(k, plan.final_name(im), show))
    for n in plan.notes:
        print("  说明  " + n)
    for w in plan.warns:
        print("  [warn] " + w)
    for i in plan.issues:
        print("  [需要决定] " + i)
    if plan.issues:
        print("  → 有 {} 项需要人决定，未改动任何文件".format(len(plan.issues)))
    elif not (plan.discard or plan.rename or plan.updates):
        print("  无需改动")
    else:
        print("  → {}".format("已执行" if applied else "dry-run，加 --apply 执行"))


def finalize_session(spec, sub, ses, apply=False, bids_dir=None, quiet=False):
    """供 convert.py 调用。返回 (状态, plan)：状态为 ok / needs_decision。"""
    plan = build_plan(spec, sub, ses, bids_dir)
    applied = False
    if apply and not plan.issues and (plan.discard or plan.rename or plan.updates):
        apply_plan(plan)
        applied = True
    if not quiet:
        report(plan, applied)
    return ("needs_decision" if plan.issues else "ok"), plan


def main():
    ap = argparse.ArgumentParser(description="按项目声明收拾 dcm2bids 产出")
    ap.add_argument("project_dir")
    ap.add_argument("--only", nargs="+", help="sub-01 或 sub-01:ses-pre")
    ap.add_argument("--bids-dir", help="对指定目录操作（默认 project.json 的 bids_dir）")
    ap.add_argument("--apply", action="store_true", help="执行（默认只 dry-run）")
    a = ap.parse_args()
    try:
        spec = bc.load_project(a.project_dir)
        rows = bc.select_rows(bc.load_mapping(spec), a.only)
        worst = 0
        for r in rows:
            status, _ = finalize_session(spec, r["sub"], r["ses"], a.apply, a.bids_dir)
            if status != "ok":
                worst = 2
            print()
    except bc.SpecError as e:
        sys.exit("错误：{}".format(e))
    sys.exit(worst)


if __name__ == "__main__":
    main()
