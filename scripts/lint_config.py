#!/usr/bin/env python3
"""
lint_config.py — 转换前检查 dcm2bids_config.json 里 dcm2bids 会静默忽略的写法

dcm2bids 3.x 不认识的键不会报错，只是不生效。最要命的是 fmap 的 IntendedFor：
  - dcm2bids 3.x 只认  "sidecar_changes": {"IntendedFor": ["<id>", ...]}
  - 顶层 "intended_for" / "intendedFor"（2.x 及更早的写法）会被**静默忽略**，
    转完所有 fmap 都没有 IntendedFor，日志里一个警告都没有。
    实测 dcm2bids 3.2.0，见 references/pitfalls.md #29。

检查项:
  [error] description 里出现顶层 intended_for / intendedFor / IntendedFor
  [error] sidecar_changes.IntendedFor 引用了不存在的 id
  [error] id 重复
  [warn]  fmap 条目没有 sidecar_changes.IntendedFor
  [warn]  description 里有 dcm2bids 3.x 不认识的顶层键

用法:
  python3 lint_config.py code/dcm2bids_config.json
  python3 lint_config.py code/dcm2bids_config.json --fix      # 把旧写法改成 sidecar_changes
  python3 lint_config.py code/dcm2bids_config.json --json
退出码: 有 error 返回 1（--fix 修完后按修复后的结果算）
"""

import argparse
import json
import re
import sys

# dcm2bids 3.x description 实际读取的键：criteria 用于匹配（sidecar.py），
# 其余作为 Acquisition(**desc) 的参数。Acquisition.__init__ 带 **kwargs，
# 其它键全被吞掉、不报错——这就是 intended_for 静默失效的机制（实测 3.2.0）
KNOWN_KEYS = {"id", "datatype", "suffix", "custom_entities", "criteria",
              "sidecar_changes"}
OLD_IFOR_KEYS = ("intended_for", "intendedFor", "IntendedFor")


def lint(cfg):
    errors, warns = [], []
    descs = cfg.get("descriptions", [])
    ids = [d.get("id") for d in descs if d.get("id")]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    for i in dup:
        errors.append(f"id 重复: {i!r}（IntendedFor 会指向错误的文件）")
    idset = set(ids)

    for n, d in enumerate(descs):
        tag = f"descriptions[{n}]" + (f" id={d['id']!r}" if d.get("id") else "") + \
              f" {d.get('datatype', '?')}/{d.get('suffix', '?')}"
        for k in OLD_IFOR_KEYS:
            if k in d:
                errors.append(f"{tag}: 顶层 {k!r} 会被 dcm2bids 3.x 静默忽略 → "
                              f"改成 \"sidecar_changes\": {{\"IntendedFor\": {json.dumps(d[k])}}}"
                              f"（或加 --fix）")
        unknown = set(d) - KNOWN_KEYS - set(OLD_IFOR_KEYS)
        if unknown:
            warns.append(f"{tag}: 未知键 {sorted(unknown)}，dcm2bids 3.x 会忽略")
        ifor = (d.get("sidecar_changes") or {}).get("IntendedFor")
        if ifor is not None:
            refs = ifor if isinstance(ifor, list) else [ifor]
            missing = [r for r in refs if isinstance(r, str) and r not in idset
                       and not r.startswith(("bids::", "func/", "ses-"))]
            if missing:
                errors.append(f"{tag}: IntendedFor 引用了不存在的 id {missing}")
        if d.get("datatype") == "fmap" and ifor is None \
                and not any(k in d for k in OLD_IFOR_KEYS):
            warns.append(f"{tag}: fmap 没有 sidecar_changes.IntendedFor")
    return errors, warns


OLD_IFOR_RE = re.compile(
    r'"(?:intended_for|intendedFor|IntendedFor)"(\s*:\s*)(\[[^\]]*\]|"[^"]*")')


def fix_text(text):
    """只改那一个键值对，保留原文件其余格式（行内数组、缩进、键顺序）。

    同一条目已有 sidecar_changes 时文本替换会产生重复键，交给 fix_obj 兜底。
    返回 (新文本, 改了几处)；不安全时返回 (None, 0)。
    """
    new, n = OLD_IFOR_RE.subn(r'"sidecar_changes"\1{"IntendedFor": \2}', text)
    if not n:
        return text, 0
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
    """结构化改写（会重排格式），仅在文本替换不安全时使用。"""
    n = 0
    for d in cfg.get("descriptions", []):
        for k in OLD_IFOR_KEYS:
            if k in d:
                val = d.pop(k)
                sc = d.setdefault("sidecar_changes", {})
                if "IntendedFor" not in sc:
                    sc["IntendedFor"] = val
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description="检查 dcm2bids config 中会被静默忽略的写法")
    ap.add_argument("config")
    ap.add_argument("--fix", action="store_true", help="把顶层 intended_for 改写成 sidecar_changes.IntendedFor")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    with open(a.config) as f:
        text = f.read()
    cfg = json.loads(text)
    fixed = 0
    if a.fix:
        new, fixed = fix_text(text)
        if new is None:                       # 文本替换不安全，退回结构化改写
            fixed = fix_obj(cfg)
            new = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
        if fixed:
            with open(a.config, "w") as f:
                f.write(new)
            cfg = json.loads(new)
    errors, warns = lint(cfg)

    if a.json:
        print(json.dumps({"config": a.config, "fixed": fixed,
                          "errors": errors, "warnings": warns}, ensure_ascii=False, indent=2))
    else:
        if fixed:
            print(f"[fix] 已把 {fixed} 处顶层 intended_for 改写为 sidecar_changes.IntendedFor")
        for e in errors:
            print(f"[error] {e}")
        for w in warns:
            print(f"[warn]  {w}")
        if not errors and not warns:
            print("[ok] config 检查通过")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
