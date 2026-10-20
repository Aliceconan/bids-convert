#!/usr/bin/env python3
"""
lint_config.py — 转换前检查 dcm2bids_config.json（对照 dcm2bids 3.2.0 源码的实际行为）

dcm2bids 3.x 对写错位置、写错名字的键**不报错、不警告、不生效**。本脚本拦住已知的几类：

  [error] description 顶层写了 intended_for / intendedFor / IntendedFor
          → 3.x 只认 "sidecar_changes": {"IntendedFor": [...]}，否则 fmap 全部没有 IntendedFor
  [error] func 条目 custom_entities 写死了 task-X，但 sidecar_changes 里没有 TaskName（或不等于 X）
          → 3.x 只在用 extractors 从 SeriesDescription 提取 task 时才自动写 TaskName；
            写死 task-X 时 sidecar 里没有 TaskName，bids-validator 报 TASK_NAME_MUST_DEFINE
  [error] sidecar_changes.IntendedFor 引用了不存在的 id；id 重复
  [error] bids_uri / search_method / dup_method / case_sensitive 取值非法
  [warn]  没有显式声明 bids_uri（默认 URI；建议写明，免得以后有人以为是 relative）
  [warn]  没有 case_sensitive: false（默认区分大小写，序列名大小写一变就漏匹配）
  [warn]  search_method 为 re 时：re.match 只锚定开头（"run_01" 也会匹配 "run_01_SBRef"），
          且 case_sensitive 对 re 不生效
  [warn]  fmap 条目没有 sidecar_changes.IntendedFor
  [warn]  description 或顶层有 dcm2bids 3.x 不认识的键

用法:
  python3 lint_config.py code/dcm2bids_config.json
  python3 lint_config.py code/dcm2bids_config.json --fix      # 改写 intended_for、补 TaskName、补 bids_uri/case_sensitive
  python3 lint_config.py code/dcm2bids_config.json --json
退出码: 有 error 返回 1（--fix 后按修复后的结果算）
"""

import argparse
import json
import re
import sys

# description 里 dcm2bids 3.x 读的键：criteria 用于匹配，其余作为 Acquisition(**desc) 参数；
# Acquisition.__init__ 带 **kwargs，其它键全被吞掉
KNOWN_KEYS = {"id", "datatype", "suffix", "custom_entities", "criteria", "sidecar_changes"}
# 顶层：dcm2bids_gen.py / sidecar.py 里 config.get(...) 读的键
KNOWN_TOP = {"descriptions", "case_sensitive", "search_method", "dup_method", "bids_uri",
             "extractors", "post_op", "compKeys", "dcm2niixOptions"}
TOP_CHOICES = {"bids_uri": ("URI", "relative"), "search_method": ("fnmatch", "re"),
               "dup_method": ("run", "dup")}
OLD_IFOR_KEYS = ("intended_for", "intendedFor", "IntendedFor")


def entities_of(desc):
    ce = desc.get("custom_entities", "")
    items = ce if isinstance(ce, list) else [ce]
    out = {}
    for it in items:
        for part in str(it).split("_"):
            if "-" in part:
                k, v = part.split("-", 1)
                out[k] = v
            elif part:
                out[part] = None          # 裸实体，由 extractors 提取
    return out


def lint(cfg):
    errors, warns = [], []
    for k in sorted(set(cfg) - KNOWN_TOP):
        if not k.startswith("_"):
            warns.append("顶层未知键 {!r}，dcm2bids 3.x 会忽略".format(k))
    for k, allowed in TOP_CHOICES.items():
        if k in cfg and cfg[k] not in allowed:
            errors.append("顶层 {} = {!r}，只能是 {}".format(k, cfg[k], "/".join(allowed)))
    if "case_sensitive" in cfg and not isinstance(cfg["case_sensitive"], bool):
        errors.append("case_sensitive 必须是 true/false，不是字符串")
    if "bids_uri" not in cfg:
        warns.append('没有声明 "bids_uri"（dcm2bids 默认 "URI"）；请显式写 "URI" 或 "relative"（或加 --fix）')
    re_mode = cfg.get("search_method") == "re"
    if re_mode:
        warns.append("search_method=re：re.match 只锚定开头，pattern 末尾要加 $；case_sensitive 对 re 不生效，"
                     "要忽略大小写用 (?i)")
    elif cfg.get("case_sensitive", True) is not False:
        warns.append('没有 "case_sensitive": false —— 默认区分大小写，序列名大小写一变就漏匹配（或加 --fix）')

    descs = cfg.get("descriptions", [])
    ids = [d.get("id") for d in descs if d.get("id")]
    for i in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append("id 重复: {!r}（IntendedFor 会指向错误的文件）".format(i))
    idset = set(ids)

    for n, d in enumerate(descs):
        tag = "descriptions[{}]".format(n) + (" id={!r}".format(d["id"]) if d.get("id") else "") + \
              " {}/{}".format(d.get("datatype", "?"), d.get("suffix", "?"))
        for k in OLD_IFOR_KEYS:
            if k in d:
                errors.append("{}: 顶层 {!r} 会被 dcm2bids 3.x 静默忽略 → 改成 "
                              "\"sidecar_changes\": {{\"IntendedFor\": {}}}（或加 --fix）".format(
                                  tag, k, json.dumps(d[k])))
        unknown = set(d) - KNOWN_KEYS - set(OLD_IFOR_KEYS)
        if unknown:
            warns.append("{}: 未知键 {}，dcm2bids 3.x 会忽略".format(tag, sorted(unknown)))
        sc = d.get("sidecar_changes") or {}
        ifor = sc.get("IntendedFor")
        if ifor is not None:
            refs = ifor if isinstance(ifor, list) else [ifor]
            missing = [r for r in refs if isinstance(r, str) and r not in idset
                       and not r.startswith(("bids::", "func/", "ses-"))]
            if missing:
                errors.append("{}: IntendedFor 引用了不存在的 id {}".format(tag, missing))
        if d.get("datatype") == "fmap" and ifor is None and not any(k in d for k in OLD_IFOR_KEYS):
            warns.append("{}: fmap 没有 sidecar_changes.IntendedFor（finalize 会按 fmap_pairing 重新配对，"
                         "但不写的话 dcm2bids 原始输出里没有任何配对信息）".format(tag))
        if d.get("datatype") == "func":
            task = entities_of(d).get("task", "absent")
            if task == "absent":
                errors.append("{}: func 条目没有 task 实体（custom_entities 里写 task-<名>）".format(tag))
            elif task is not None and sc.get("TaskName") != task:
                errors.append("{}: custom_entities 写死 task-{}，sidecar_changes.TaskName 必须是 {!r}"
                              "（现在是 {!r}；dcm2bids 不会自动填，或加 --fix）".format(
                                  tag, task, task, sc.get("TaskName")))
        crit = d.get("criteria") or {}
        if re_mode:
            for key, pat in crit.items():
                pats = pat.get("any", []) if isinstance(pat, dict) else [pat]
                for p in pats:
                    if isinstance(p, str) and not p.endswith("$"):
                        warns.append("{}: re 模式下 {} 的 {!r} 没以 $ 结尾，会做前缀匹配".format(tag, key, p))
    return errors, warns


OLD_IFOR_RE = re.compile(
    r'"(?:intended_for|intendedFor|IntendedFor)"(\s*:\s*)(\[[^\]]*\]|"[^"]*")')


def fix_text(text):
    """只改那一个键值对，保留原文件其余格式。返回 (新文本, 改动数)；文本替换不安全时返回 (None, 0)。

    正则分不清嵌套层级：已经正确写在 sidecar_changes 里的 "IntendedFor" 也会被命中（旧版的 bug：
    对正确的 config 跑 --fix 会套两层 sidecar_changes）。所以只有命中数恰好等于 description 顶层
    旧写法的个数时才用文本替换。"""
    cfg = json.loads(text)
    n_old = sum(1 for d in cfg.get("descriptions", []) for k in OLD_IFOR_KEYS if k in d)
    if n_old == 0:
        return text, 0
    if len(OLD_IFOR_RE.findall(text)) != n_old:
        return None, 0
    new, n = OLD_IFOR_RE.subn(r'"sidecar_changes"\1{"IntendedFor": \2}', text)
    try:
        json.loads(new, object_pairs_hook=_no_dup_keys)
    except ValueError:
        return None, 0
    return new, n


def _no_dup_keys(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def fix_obj(cfg):
    """结构化改写：intended_for → sidecar_changes；补 TaskName。返回改动数。"""
    n = 0
    for d in cfg.get("descriptions", []):
        for k in OLD_IFOR_KEYS:
            if k in d:
                val = d.pop(k)
                sc = d.setdefault("sidecar_changes", {})
                sc.setdefault("IntendedFor", val)
                n += 1
        if d.get("datatype") == "func":
            task = entities_of(d).get("task")
            if task and (d.get("sidecar_changes") or {}).get("TaskName") != task:
                d.setdefault("sidecar_changes", {})["TaskName"] = task
                n += 1
    return n


def fix_top(cfg):
    """补顶层 bids_uri / case_sensitive，放在 descriptions 前面。"""
    n = 0
    new = {}
    if "bids_uri" not in cfg:
        new["bids_uri"] = "URI"
        n += 1
    if cfg.get("search_method") != "re" and cfg.get("case_sensitive", True) is not False:
        new["case_sensitive"] = False
        n += 1
    if n:
        rest = dict((k, v) for k, v in cfg.items() if k not in new)
        cfg.clear()
        cfg.update(new)
        cfg.update(rest)
    return n


def main():
    ap = argparse.ArgumentParser(description="检查 dcm2bids config 中会被静默忽略或必然出错的写法")
    ap.add_argument("config")
    ap.add_argument("--fix", action="store_true",
                    help="改写 intended_for、补 TaskName、补 bids_uri=URI 与 case_sensitive=false")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    with open(a.config) as f:
        text = f.read()
    cfg = json.loads(text)
    fixed = 0
    if a.fix:
        new, fixed = fix_text(text)          # 只有 intended_for 时尽量保留原格式
        cfg = json.loads(new) if new is not None else cfg
        if new is None:
            fixed = 0                        # 交给 fix_obj 结构化改写
        more = fix_obj(cfg) + fix_top(cfg)
        if more or new is None:
            new = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
            fixed += more
        if fixed:
            with open(a.config, "w") as f:
                f.write(new)
            cfg = json.loads(new)
    errors, warns = lint(cfg)

    if a.json:
        print(json.dumps({"config": a.config, "fixed": fixed, "errors": errors, "warnings": warns},
                         ensure_ascii=False, indent=2))
    else:
        if fixed:
            print("[fix] 改了 {} 处".format(fixed))
        for e in errors:
            print("[error] " + e)
        for w in warns:
            print("[warn]  " + w)
        if not errors and not warns:
            print("[ok] config 检查通过")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
