"""测试用的合成项目：只造 NIfTI 头 + sidecar，不需要真实影像。"""
import gzip
import json
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))


def nii(path, vols, center=None):
    """center=(x,y,z) 时写一个轴向的 sform（体素 1mm，扫描框中心在 center）。"""
    hdr = bytearray(352)
    if vols > 1:
        struct.pack_into("<8h", hdr, 40, 4, 8, 8, 4, vols, 1, 1, 1)
    else:
        struct.pack_into("<8h", hdr, 40, 3, 8, 8, 4, 1, 1, 1, 1)
    if center is not None:
        struct.pack_into("<h", hdr, 254, 1)
        half = (3.5, 3.5, 1.5)
        for i, off in enumerate((280, 296, 312)):
            row = [0.0, 0.0, 0.0, center[i] - half[i]]
            row[i] = 1.0
            struct.pack_into("<4f", hdr, off, *row)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(str(path), "wb") as f:
        f.write(bytes(hdr))


def hms(sec):
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return "{:02d}:{:02d}:{:09.6f}".format(int(h), int(m), s)


class FakeProject(object):
    """<tmp>/code/{project.json,protocol.tsv,decisions.tsv,dcm2bids_config.json,participants_mapping.tsv}
    与 <tmp>/bids/sub-XX/... 。"""

    def __init__(self, protocol, project=None, config=None, decisions=None, subs=("sub-01",)):
        self.root = Path(tempfile.mkdtemp(prefix="bidsconv_test_"))
        self.code = self.root / "code"
        self.code.mkdir()
        self.bids = self.root / "bids"
        self.bids.mkdir()
        proj = {"name": "test", "raw_root": str(self.root / "raw"), "fmap_pairing": "after",
                "unmatched_func": "discard"}
        proj.update(project or {})
        (self.code / "project.json").write_text(json.dumps(proj))
        lines = ["task\trun\tvolumes\ttolerance"]
        for task, runs in protocol.items():
            for i, v in enumerate(runs, 1):
                lines.append("{}\t{}\t{}\t0".format(task, i, v))
        (self.code / "protocol.tsv").write_text("\n".join(lines) + "\n")
        cfg = {"case_sensitive": False, "bids_uri": "URI", "descriptions": []}
        cfg.update(config or {})
        (self.code / "dcm2bids_config.json").write_text(json.dumps(cfg))
        self.set_decisions(decisions or [])
        (self.code / "participants_mapping.tsv").write_text(
            "participant_id\tdicom_dir\n" + "".join("{}\tS{}\n".format(s, i) for i, s in enumerate(subs)))

    def set_decisions(self, rows):
        txt = "participant_id\tsession\taction\ttarget\tvalue\treason\n"
        txt += "".join("\t".join(r) + "\n" for r in rows)
        (self.code / "decisions.tsv").write_text(txt)

    def add(self, sub, datatype, name, vols, sn, sd, t, tr=2.0, center=None, **meta):
        d = self.bids / sub / datatype
        nii(d / (name + ".nii.gz"), vols, center)
        m = {"SeriesNumber": sn, "SeriesDescription": sd, "AcquisitionTime": hms(t),
             "RepetitionTime": tr}
        m.update(meta)
        (d / (name + ".json")).write_text(json.dumps(m))

    def files(self, sub, datatype):
        d = self.bids / sub / datatype
        return sorted(p.name for p in d.iterdir()) if d.exists() else []

    def meta(self, sub, datatype, name):
        return json.loads((self.bids / sub / datatype / (name + ".json")).read_text())

    def cleanup(self):
        shutil.rmtree(str(self.root))
