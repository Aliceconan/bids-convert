#!/usr/bin/env python3
"""convert.py — 按 participants_mapping.tsv 并行转换：dcm2niix 缓存 → dcm2bids 匹配 → finalize → physio。

每个 session 的流程：
  1. dcm2niix 输出缓存在 work/dcm2niix/<sub[_ses]>/（有 .complete 标记就复用，
     --refresh-cache 才重跑 dcm2niix）。
  2. 清掉该 session 旧的 BIDS 输出和 dcm2bids 的 tmp，把缓存**硬链接**（或复制）进
     bids/tmp_dcm2bids/<sub[_ses]>/，再调 dcm2bids（不加 --force_dcm2bids，它看到 tmp
     非空就跳过 dcm2niix，直接匹配）。
     为什么不直接复用 dcm2bids 的 tmp：dcm2bids 匹配成功后会把 NIfTI 从 tmp **移走**，
     tmp 里只剩没匹配上的。旧版「删 BIDS 输出 + 不加 force 重跑」实测产出为空、退出码 0。
     为什么不用 dcm2bids --skip_dcm2niix：它内部用 copytree(dirs_exist_ok=)，要 Python ≥3.8。
  3. 检查产出非空、没有「Several Pairing」（一个 series 匹配了多条规则）。
  4. finalize.py --apply（按协议表分配 run、剔废片、配 fmap、补 TaskName）。
     有待人工决定的事项就停在这一步，状态记为 needs_decision。
  5. mapping 里 physio_mode 为 dicom/file 时转生理记录（physio_to_bids.py）。

所以「改了 config / decisions 之后重跑」永远是安全的：每次都从缓存重新匹配，几分钟内完成，
不会残留旧文件，也不会丢数据。

用法：
  python3 convert.py <project_dir>                       # 全部 session
  python3 convert.py <project_dir> --only sub-03 sub-05:ses-post
  python3 convert.py <project_dir> --refresh-cache       # 换了 dcm2niix 版本 / 改了 dcm2niixOptions
  python3 convert.py <project_dir> --no-finalize         # 只看 dcm2bids 原始匹配
状态：ok / needs_decision（有待人工决定的事项，停在 dcm2bids 原始输出）/ failed / physio_failed（影像已完成，生理记录失败）
退出码：0 全部完成；2 有 session 需要人工决定；1 有 session 失败
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bids_common as bc  # noqa: E402
import finalize  # noqa: E402
import lint_config  # noqa: E402

DCM2BIDS_DEFAULT_OPTS = "-b y -ba y -z y -f '%3s_%f_%p_%t'"


def sh(cmd, log, cwd=None):
    """跑命令，stdout+stderr 追加进 log；返回退出码。"""
    with open(str(log), "a") as f:
        f.write("\n$ {}\n".format(" ".join(shlex.quote(str(c)) for c in cmd)))
        f.flush()
        p = subprocess.Popen([str(c) for c in cmd], stdout=f, stderr=subprocess.STDOUT,
                             cwd=str(cwd) if cwd else None)
        return p.wait()


def tool_version(exe):
    try:
        out = subprocess.check_output([exe, "-v"], stderr=subprocess.STDOUT, universal_newlines=True)
    except (OSError, subprocess.CalledProcessError) as e:
        out = getattr(e, "output", "") or ""
    return out.strip().splitlines()[-1] if out.strip() else "unknown"


def ensure_cache(spec, row, opts, refresh, log):
    """dcm2niix 输出缓存。标记文件记录 DICOM 路径、dcm2niix 版本和参数，任一变化就重建。"""
    cache = Path(spec["work_dir"]) / "dcm2niix" / bc.prefix_of(row["sub"], row["ses"])
    marker = cache / ".complete"
    want = {"dicom": str(row["dicom_path"]), "dcm2niix": tool_version(spec["dcm2niix"]), "options": opts}
    if marker.exists() and not refresh:
        try:
            if json.loads(marker.read_text()) == want:
                return cache, True
        except ValueError:
            pass
    if cache.exists():
        shutil.rmtree(str(cache))
    cache.mkdir(parents=True)
    rc = sh([spec["dcm2niix"]] + shlex.split(opts) + ["-o", cache, row["dicom_path"]], log)
    if rc != 0 or not list(cache.glob("*.json")):
        raise RuntimeError("dcm2niix 失败（退出码 {}），见 {}".format(rc, log))
    marker.write_text(json.dumps(want, indent=1))
    return cache, False


def populate_tmp(spec, cache, tmp):
    if tmp.exists():
        shutil.rmtree(str(tmp))
    tmp.mkdir(parents=True)
    n = 0
    for f in cache.iterdir():
        if f.name.startswith("."):
            continue
        dst = tmp / f.name
        if spec["cache_mode"] == "hardlink":
            try:
                os.link(str(f), str(dst))
            except OSError:          # 跨文件系统等
                shutil.copy2(str(f), str(dst))
        else:
            shutil.copy2(str(f), str(dst))
        n += 1
    return n


def clean_session(spec, row):
    d = bc.session_dir(spec, row["sub"], row["ses"])
    if d.exists():
        shutil.rmtree(str(d))
    # 上一次转换剔除的文件：重转会从缓存重新产生，留着只会堆出一堆时间戳目录
    disc = Path(spec["work_dir"]) / "discarded" / bc.prefix_of(row["sub"], row["ses"])
    if disc.exists():
        shutil.rmtree(str(disc))
    if row["ses"]:                           # 被试目录空了也删掉（同被试别的 session 可能正在并行写，失败就算了）
        try:
            d.parent.rmdir()
        except OSError:
            pass


def parse_dcm2bids_log(log):
    unmatched, several = [], []
    txt = re.sub(r"\x1b\[[0-9;]*m", "", Path(log).read_text(errors="replace"))   # 去掉终端颜色码
    for line in txt.splitlines():
        if "No Pairing" in line and "<-" in line:
            unmatched.append(line.split("<-", 1)[1].strip())
        if "Several Pairing" in line and "<-" in line:
            several.append(line.split("<-", 1)[1].strip())
    return unmatched, several


def convert_one(spec, row, opts, args):
    prefix = bc.prefix_of(row["sub"], row["ses"])
    log = Path(spec["log_dir"]) / "{}.log".format(prefix)
    log.write_text("=== {} {} ===\nDICOM: {}\n".format(time.strftime("%F %T"), prefix, row["dicom_path"]))
    res = {"session": prefix, "status": "failed", "detail": "", "log": str(log)}
    t0 = time.time()
    try:
        if not Path(row["dicom_path"]).is_dir():
            raise RuntimeError("DICOM 目录不存在：{}".format(row["dicom_path"]))
        cache, reused = ensure_cache(spec, row, opts, args.refresh_cache, log)
        clean_session(spec, row)
        tmp = Path(spec["bids_dir"]) / "tmp_dcm2bids" / prefix
        populate_tmp(spec, cache, tmp)
        cmd = [spec["dcm2bids"], "-d", row["dicom_path"], "-p", row["sub"][4:],
               "-c", spec["config_path"], "-o", spec["bids_dir"], "-l", "INFO"]
        if row["ses"]:
            cmd[5:5] = ["-s", row["ses"][4:]]
        rc = sh(cmd, log)
        if rc != 0:
            raise RuntimeError("dcm2bids 退出码 {}".format(rc))
        unmatched, several = parse_dcm2bids_log(log)
        res["unmatched_series"] = unmatched
        sd = bc.session_dir(spec, row["sub"], row["ses"])
        if several:
            raise RuntimeError("{} 个 series 同时匹配了多条规则（dcm2bids 会跳过它们）：{}".format(
                len(several), several[:5]))
        if not sd.is_dir() or not list(sd.rglob("*.nii*")):
            raise RuntimeError("dcm2bids 没有产出任何文件（config 一条都没匹配上？）")
        res["detail"] = "dcm2niix 缓存{}".format("复用" if reused else "新建")
        if args.no_finalize:
            res["status"] = "converted"
        else:
            status, plan = finalize.finalize_session(spec, row["sub"], row["ses"], apply=True, quiet=True)
            with open(str(log), "a") as f:
                f.write("\n--- finalize ---\n")
                for i in plan.issues:
                    f.write("[需要决定] {}\n".format(i))
                for w in plan.warns:
                    f.write("[warn] {}\n".format(w))
            res["warnings"] = plan.warns
            if status != "ok":
                res["status"] = "needs_decision"
                res["issues"] = plan.issues
            else:
                res["status"] = "ok"
                if row["physio_mode"] != "none":
                    try:
                        import physio_to_bids
                        pres = physio_to_bids.process_session(spec, row, log=log)
                    except Exception as e:  # noqa: BLE001
                        res["status"] = "physio_failed"
                        res["detail"] += "；生理记录失败：{}: {}".format(type(e).__name__, e)
                    else:
                        res["physio"] = pres
                        if pres.get("problems"):
                            res["warnings"] = res.get("warnings", []) + pres["problems"]
    except Exception as e:  # noqa: BLE001 —— 一个 session 失败不影响其它
        res["status"] = "failed"
        res["detail"] = "{}: {}".format(type(e).__name__, e)
    res["seconds"] = round(time.time() - t0)
    return res


def main():
    ap = argparse.ArgumentParser(description="并行转换 DICOM → BIDS")
    ap.add_argument("project_dir")
    ap.add_argument("--only", nargs="+", help="sub-01 或 sub-01:ses-pre")
    ap.add_argument("-j", "--jobs", type=int, help="并行 session 数（默认 project.json 的 jobs）")
    ap.add_argument("--refresh-cache", action="store_true", help="重跑 dcm2niix")
    ap.add_argument("--no-finalize", action="store_true", help="只跑 dcm2bids，不收拾")
    args = ap.parse_args()

    try:
        spec = bc.load_project(args.project_dir)
        rows = bc.select_rows(bc.load_mapping(spec), args.only)
        cfg = bc.load_config(spec)
    except bc.SpecError as e:
        sys.exit("错误：{}".format(e))
    errors, warns = lint_config.lint(cfg)
    for w in warns:
        print("[config warn] " + w)
    if errors:
        for e in errors:
            print("[config error] " + e)
        sys.exit("config 检查未通过，已停止（lint_config.py --fix 可自动改一部分）")
    for exe in (spec["dcm2bids"], spec["dcm2niix"]):
        if not shutil.which(exe):
            sys.exit("找不到可执行文件 {}（在 project.json 里写绝对路径）".format(exe))
    if any(r["physio_mode"] == "dicom" for r in rows):
        try:
            import pydicom  # noqa: F401
        except ImportError:
            sys.exit("有 session 的 physio_mode=dicom，需要 pydicom：用 dcm2bids 所在环境的 python 运行 convert.py\n"
                     "  （当前解释器 {}）".format(sys.executable))

    Path(spec["log_dir"]).mkdir(parents=True, exist_ok=True)
    Path(spec["bids_dir"]).mkdir(parents=True, exist_ok=True)
    opts = cfg.get("dcm2niixOptions", DCM2BIDS_DEFAULT_OPTS)
    jobs = args.jobs or spec["jobs"]
    print("转换 {} 个 session，并行 {}，日志在 {}".format(len(rows), jobs, spec["log_dir"]))
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        results = list(ex.map(lambda r: convert_one(spec, r, opts, args), rows))

    print("\n{:<22} {:<15} {:>6}  {}".format("session", "状态", "秒", "说明"))
    for r in results:
        print("{:<22} {:<15} {:>6}  {}".format(r["session"], r["status"], r["seconds"], r["detail"]))
        for i in r.get("issues", []):
            print("    [需要决定] " + i.replace("\n", "\n    "))
        for w in r.get("warnings", []):
            print("    [warn] " + w)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(spec["log_dir"]) / "convert_{}.json".format(stamp)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print("\n明细：{}".format(out))
    if any(r["status"] in ("failed", "physio_failed") for r in results):
        sys.exit(1)
    if any(r["status"] == "needs_decision" for r in results):
        print("有 session 需要人工决定：把决定写进 code/decisions.tsv，然后对这些 session 重跑 convert.py --only …")
        sys.exit(2)


if __name__ == "__main__":
    main()
