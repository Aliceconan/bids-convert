#!/usr/bin/env python3
"""init_metadata.py — 生成数据集级元数据：dataset_description.json、participants.tsv/json、README、.bidsignore。

  * dataset_description.json：Name / BIDSVersion / DatasetType 来自 project.json；Authors、License
    只在 project.json 里填了才写（空字符串字段会被 validator 报，宁可不写——Authors 要问用户）。
  * participants.tsv：每次按 mapping 重建（被试 = mapping 里出现过的 participant_id）。
    project.json 的 participants_demographics 为 true 时，从 scout 结果的 PatientSex/PatientAge
    补 sex/age 两列（BIDS 标准列，去标识化；姓名、原始编号、出生日期永远不写）。
  * README、.bidsignore：不存在才创建，已有的不动（README 是给人写的，脚本只给骨架）。

用法：python3 init_metadata.py <project_dir> [--force-description]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bids_common as bc  # noqa: E402

BIDS_VERSION = "1.9.0"


def demographics(spec, sub, ses_list):
    for ses in ses_list:
        p = Path(spec["work_dir"]) / "scout" / bc.prefix_of(sub, ses) / "session.json"
        if p.exists():
            info = json.loads(p.read_text())
            sex = {"F": "female", "M": "male", "O": "other"}.get(info.get("PatientSex", ""), "n/a")
            m = re.match(r"^0*(\d+)Y$", info.get("PatientAge", ""))
            return (m.group(1) if m else "n/a"), sex
    return "n/a", "n/a"


def main():
    ap = argparse.ArgumentParser(description="生成 BIDS 数据集级元数据")
    ap.add_argument("project_dir")
    ap.add_argument("--force-description", action="store_true", help="覆盖已有的 dataset_description.json")
    a = ap.parse_args()
    try:
        spec = bc.load_project(a.project_dir)
        rows = bc.load_mapping(spec)
    except bc.SpecError as e:
        sys.exit("错误：{}".format(e))
    bids = Path(spec["bids_dir"])
    bids.mkdir(parents=True, exist_ok=True)

    dd = bids / "dataset_description.json"
    if not dd.exists() or a.force_description:
        desc = {"Name": spec["name"] or spec["project_dir"].name, "BIDSVersion": BIDS_VERSION,
                "DatasetType": "raw"}
        if spec["authors"]:
            desc["Authors"] = spec["authors"]
        if spec["license"]:
            desc["License"] = spec["license"]
        desc["GeneratedBy"] = [{"Name": "dcm2bids"}, {"Name": "bids-convert (finalize.py)"}]
        dd.write_text(json.dumps(desc, indent=4, ensure_ascii=False) + "\n")
        print("写入 {}".format(dd))
        if not spec["authors"]:
            print("  [提醒] project.json 没填 authors —— 上传 OpenNeuro 前要问用户补上")

    subs = []
    for r in rows:
        if r["sub"] not in subs:
            subs.append(r["sub"])
    subs.sort()
    with_demo = spec["participants_demographics"]
    lines = ["participant_id" + ("\tage\tsex" if with_demo else "")]
    for s in subs:
        if with_demo:
            age, sex = demographics(spec, s, [r["ses"] for r in rows if r["sub"] == s])
            lines.append("{}\t{}\t{}".format(s, age, sex))
        else:
            lines.append(s)
    (bids / "participants.tsv").write_text("\n".join(lines) + "\n")
    pj = {"participant_id": {"Description": "Unique participant identifier"}}
    if with_demo:
        pj["age"] = {"Description": "Age at first scan (DICOM PatientAge)", "Units": "year"}
        pj["sex"] = {"Description": "Sex (DICOM PatientSex)",
                     "Levels": {"female": "female", "male": "male", "other": "other"}}
    (bids / "participants.json").write_text(json.dumps(pj, indent=4) + "\n")
    print("写入 participants.tsv（{} 名被试{}）".format(len(subs), "，含 age/sex" if with_demo else ""))

    readme = bids / "README"
    if not readme.exists():
        readme.write_text(
            "# {}\n\n（数据集说明：采集参数、被试、已知问题。由人补充。）\n\n"
            "转换流程与人工决策见 code/decisions.tsv 与 code/decision_log.md。\n".format(spec["name"]))
        print("写入 README 骨架（请补充内容）")
    ign = bids / ".bidsignore"
    if not ign.exists():
        ign.write_text("tmp_dcm2bids/\n")
        print("写入 .bidsignore")


if __name__ == "__main__":
    main()
