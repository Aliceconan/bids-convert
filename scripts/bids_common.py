#!/usr/bin/env python3
"""bids-convert 各脚本共用的小工具：项目声明文件、BIDS 文件名、sidecar、NIfTI 头。

只依赖标准库，兼容 Python 3.6（服务器节点默认的 python3）。
项目目录约定（见 references/project_spec.md）：

    <project>/
      code/dcm2bids_config.json      匹配规则（dcm2bids 原生格式）
      code/participants_mapping.tsv  participant_id [session] dicom_dir [physio_mode] [physio_dir]
      code/project.json              项目级设置（路径、fmap 配对规则、默认策略）
      code/protocol.tsv              task run volumes [tolerance]
      code/decisions.tsv             逐 session 的人工决策（可选）
      code/logs/                     日志与状态
      bids/                          BIDS 输出
      work/                          dcm2niix 缓存、侦察结果、被剔除的文件
"""
import csv
import gzip
import json
import re
import struct
from pathlib import Path

# BIDS 1.9 entity 顺序（文件名里 entity 必须按这个顺序出现）
ENTITY_ORDER = ["sub", "ses", "sample", "task", "tracksys", "acq", "ce", "trc",
                "stain", "rec", "dir", "run", "mod", "echo", "flip", "inv", "mt",
                "part", "proc", "hemi", "space", "split", "recording", "chunk",
                "seg", "res", "den", "label", "desc"]

IMAGE_EXTS = (".nii.gz", ".nii")

PROJECT_DEFAULTS = {
    "name": "",
    "raw_root": "",
    "bids_dir": "bids",
    "work_dir": "work",
    "dcm2bids": "dcm2bids",
    "dcm2niix": "dcm2niix",
    "jobs": 4,
    "cache_mode": "hardlink",      # hardlink | copy
    "fmap_pairing": "",            # 必填：after | before | nearest | index | all | none
    "anat_duplicates": "ask",      # ask | first | last | all
    "unmatched_func": "ask",       # ask | discard
    "unpaired_fmap": "ask",        # ask | discard | keep
    "authors": [],
    "license": "",
    "participants_demographics": False,
}

CHOICES = {
    "cache_mode": ("hardlink", "copy"),
    "fmap_pairing": ("after", "before", "nearest", "index", "all", "none"),
    "anat_duplicates": ("ask", "first", "last", "all"),
    "unmatched_func": ("ask", "discard"),
    "unpaired_fmap": ("ask", "discard", "keep"),
}


class SpecError(Exception):
    """项目声明文件缺失或写错。"""


# ---------------------------------------------------------------- 项目声明

def load_project(project_dir):
    """读 code/project.json，补默认值，把相对路径解析成绝对路径。"""
    project_dir = Path(project_dir).resolve()
    p = project_dir / "code" / "project.json"
    if not p.exists():
        raise SpecError("找不到 {}（从 templates/project.json 复制一份）".format(p))
    spec = dict(PROJECT_DEFAULTS)
    try:
        spec.update(json.loads(p.read_text()))
    except ValueError as e:
        raise SpecError("{} 不是合法 JSON: {}".format(p, e))
    unknown = set(spec) - set(PROJECT_DEFAULTS) - {"_comment"}
    if unknown:
        raise SpecError("{} 有不认识的键 {}（拼写错误会被当成没写）".format(p, sorted(unknown)))
    for k, allowed in CHOICES.items():
        if spec[k] not in allowed:
            hint = "（必填：没有 fmap 的项目写 none）" if k == "fmap_pairing" and not spec[k] else ""
            raise SpecError("{}: {} = {!r}，只能是 {}{}".format(p, k, spec[k], "/".join(allowed), hint))
    for k in ("bids_dir", "work_dir"):
        v = Path(spec[k])
        spec[k] = v if v.is_absolute() else project_dir / v
    spec["project_dir"] = project_dir
    spec["code_dir"] = project_dir / "code"
    spec["log_dir"] = project_dir / "code" / "logs"
    spec["config_path"] = project_dir / "code" / "dcm2bids_config.json"
    return spec


def read_tsv(path):
    """按表头读 TSV，返回 list[dict]；跳过空行和以 # 开头的行。"""
    path = Path(path)
    if not path.exists():
        return []
    with open(str(path), newline="") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    rows = list(csv.DictReader(lines, delimiter="\t"))
    return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in rows]


def norm_sub(x):
    x = x.strip()
    return x if x.startswith("sub-") else "sub-" + x


def norm_ses(x):
    x = (x or "").strip()
    if not x:
        return ""
    return x if x.startswith("ses-") else "ses-" + x


def load_mapping(spec):
    """participants_mapping.tsv → list[dict]，按表头读（session 列可选）。"""
    p = spec["code_dir"] / "participants_mapping.tsv"
    rows = read_tsv(p)
    if not rows:
        raise SpecError("{} 不存在或为空".format(p))
    miss = {"participant_id", "dicom_dir"} - set(rows[0])
    if miss:
        raise SpecError("{} 缺列 {}（必需：participant_id, dicom_dir；可选：session, "
                        "physio_mode, physio_dir）".format(p, sorted(miss)))
    out, seen = [], set()
    for r in rows:
        sub, ses = norm_sub(r["participant_id"]), norm_ses(r.get("session", ""))
        if (sub, ses) in seen:
            raise SpecError("{}: {} {} 出现了两次".format(p, sub, ses))
        seen.add((sub, ses))
        d = Path(r["dicom_dir"])
        if not d.is_absolute():
            if not spec.get("raw_root"):
                raise SpecError("{}: dicom_dir 是相对路径，但 project.json 没写 raw_root".format(p))
            d = Path(spec["raw_root"]) / d
        pdir = r.get("physio_dir", "")
        if pdir and not Path(pdir).is_absolute() and spec.get("raw_root"):
            pdir = str(Path(spec["raw_root"]) / pdir)
        mode = (r.get("physio_mode") or "none").lower()
        if mode not in ("none", "dicom", "file"):
            raise SpecError("{}: {} physio_mode = {!r}，只能是 none/dicom/file".format(p, sub, mode))
        row = dict(r)
        row.update({"sub": sub, "ses": ses, "dicom_path": d,
                    "physio_mode": mode, "physio_dir": pdir})
        out.append(row)
    return out


def prefix_of(sub, ses):
    return "{}_{}".format(sub, ses) if ses else sub


def session_dir(spec, sub, ses):
    d = Path(spec["bids_dir"]) / sub
    return d / ses if ses else d


def select_rows(rows, only):
    """--only sub-01 sub-02:ses-pre → 过滤 mapping（只写 sub 表示该被试所有 session）。"""
    if not only:
        return rows
    out = []
    for o in only:
        sub, _, ses = o.partition(":")
        sub, ses = norm_sub(sub), norm_ses(ses)
        hit = [r for r in rows if r["sub"] == sub and (not ses or r["ses"] == ses)]
        if not hit:
            raise SpecError("mapping 里没有 {} {}".format(sub, ses))
        out += [r for r in hit if r not in out]
    return out


def load_protocol(spec):
    """protocol.tsv → {task: {run(int): (volumes, tolerance)}}。"""
    p = spec["code_dir"] / "protocol.tsv"
    proto = {}
    for r in read_tsv(p):
        try:
            task, run, vol = r["task"], int(r["run"]), int(r["volumes"])
            tol = int(r.get("tolerance") or 0)
        except (KeyError, ValueError) as e:
            raise SpecError("{}: 行 {} 写错（需要 task/run/volumes，tolerance 可选）: {}".format(p, r, e))
        proto.setdefault(task, {})
        if run in proto[task]:
            raise SpecError("{}: task-{} run {} 重复".format(p, task, run))
        proto[task][run] = (vol, tol)
    return proto


def load_decisions(spec, sub, ses):
    """decisions.tsv 中属于该 session 的行。session 列留空表示对该被试所有 session 生效。"""
    out = []
    for r in read_tsv(spec["code_dir"] / "decisions.tsv"):
        if not r.get("participant_id") or norm_sub(r["participant_id"]) != sub:
            continue
        rses = norm_ses(r.get("session", ""))
        if rses and rses != ses:
            continue
        out.append(r)
    return out


def load_config(spec):
    return json.loads(Path(spec["config_path"]).read_text())


# ---------------------------------------------------------------- BIDS 文件名

def split_image(path):
    """'.../sub-01_task-x_bold.nii.gz' → ('.../sub-01_task-x_bold', '.nii.gz')"""
    s = str(path)
    for ext in IMAGE_EXTS:
        if s.endswith(ext):
            return s[: -len(ext)], ext
    raise ValueError("不是 NIfTI: {}".format(path))


def parse_name(name):
    """'sub-01_task-x_run-02_bold' → ({'sub':'01','task':'x','run':'02'}, 'bold')。
    不含 '-' 的中间片段放进 ents['_extra']。"""
    parts = name.split("_")
    suffix = parts[-1]
    ents, extra = {}, []
    for p in parts[:-1]:
        if "-" in p:
            k, v = p.split("-", 1)
            ents[k] = v
        else:
            extra.append(p)
    if extra:
        ents["_extra"] = extra
    return ents, suffix


def build_name(ents, suffix):
    known = ["{}-{}".format(k, ents[k]) for k in ENTITY_ORDER if ents.get(k)]
    other = ["{}-{}".format(k, v) for k, v in ents.items()
             if k not in ENTITY_ORDER and k != "_extra" and v]
    return "_".join(known + other + list(ents.get("_extra", [])) + [suffix])


# ---------------------------------------------------------------- sidecar / NIfTI

def nifti_volumes(path):
    """读 NIfTI 头的第 4 维长度，不解压整个文件。"""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(str(path), "rb") as f:
        hdr = f.read(352)
    if len(hdr) < 56:
        return 0
    dims = struct.unpack_from("<8h", hdr, 40)
    if not 1 <= dims[0] <= 7:                 # 大端存储
        dims = struct.unpack_from(">8h", hdr, 40)
    return dims[4] if dims[0] >= 4 else 1


def nifti_geometry(path):
    """读 NIfTI 头：返回 (扫描框中心 xyz mm, 层面法向单位向量)；没有 sform/qform 时返回 None。

    只用 sform（dcm2niix 总会写）；中心 = affine · ((dim-1)/2)，法向 = affine 第 3 列归一化。"""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(str(path), "rb") as f:
        hdr = f.read(352)
    if len(hdr) < 328:
        return None
    end = "<"
    dims = struct.unpack_from("<8h", hdr, 40)
    if not 1 <= dims[0] <= 7:
        end = ">"
        dims = struct.unpack_from(">8h", hdr, 40)
    sform_code = struct.unpack_from(end + "h", hdr, 254)[0]
    if sform_code <= 0:
        return None
    rows = [struct.unpack_from(end + "4f", hdr, off) for off in (280, 296, 312)]
    half = [(dims[i + 1] - 1) / 2.0 for i in range(3)]
    center = [r[0] * half[0] + r[1] * half[1] + r[2] * half[2] + r[3] for r in rows]
    nz = [r[2] for r in rows]
    norm = sum(v * v for v in nz) ** 0.5 or 1.0
    return center, [v / norm for v in nz]


def parse_time(s):
    """'14:04:28.5425' 或 DICOM TM '140428.5425' → 自零点起的秒数；解析不了返回 None。

    dcm2niix v1.0.20250505 写 AcquisitionTime 时秒数不补零（实测 "11:41:1.870000"），
    所以时、分、秒都按 1–2 位接受。"""
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r"^(\d{1,2}):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$", s) or \
        re.match(r"^(\d{2})(\d{2})(\d{2}(?:\.\d+)?)$", s)
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def fmt_time(sec):
    if sec is None:
        return "?"
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return "{:02d}:{:02d}:{:06.3f}".format(int(h), int(m), s)


class Image(object):
    """BIDS 里的一个影像（nii + json），附带配对决策需要的元数据。"""

    def __init__(self, img_path):
        self.img = Path(img_path)
        stem, self.ext = split_image(self.img)
        self.stem = Path(stem)
        self.json = Path(stem + ".json")
        self.datatype = self.img.parent.name
        self.ents, self.suffix = parse_name(self.stem.name)
        self.meta = json.loads(self.json.read_text()) if self.json.exists() else {}
        self.sn = self.meta.get("SeriesNumber")
        self.sd = self.meta.get("SeriesDescription", "")
        self.time = parse_time(self.meta.get("AcquisitionTime"))
        self.tr = self.meta.get("RepetitionTime")
        self._vols = None
        self._geom = False

    @property
    def geometry(self):
        if self._geom is False:
            try:
                self._geom = nifti_geometry(self.img)
            except (OSError, struct.error):
                self._geom = None
        return self._geom

    @property
    def volumes(self):
        if self._vols is None:
            self._vols = nifti_volumes(self.img)
        return self._vols

    @property
    def end_time(self):
        if self.time is None:
            return None
        return self.time + (self.volumes * self.tr if self.tr else 0)

    def sort_key(self):
        return (self.time if self.time is not None else 1e9,
                self.sn if isinstance(self.sn, int) else 1e9, self.stem.name)

    def label(self):
        return "{} (SN{} {!r} {})".format(self.stem.name, self.sn, self.sd, fmt_time(self.time))


def session_images(sess_dir):
    """session 目录下各 datatype 的所有影像（不含 physio/events 等表格）。"""
    out = []
    for dt in sorted(p for p in Path(sess_dir).iterdir() if p.is_dir()):
        for f in sorted(dt.iterdir()):
            if f.name.endswith(IMAGE_EXTS):
                out.append(Image(f))
    return sorted(out, key=Image.sort_key)


def intended_for_entry(bids_dir, img_path, style):
    """IntendedFor 条目。style 'URI' → bids::sub-XX/...；'relative' → 相对被试目录。"""
    rel = Path(img_path).resolve().relative_to(Path(bids_dir).resolve())
    if style == "relative":
        return str(Path(*rel.parts[1:]))
    return "bids::" + str(rel)
