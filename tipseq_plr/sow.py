"""
Statement-of-Work compiler: turn a plan into an executable STAR run.

A planning tool (Augmentiv, a PI's email, a protocols.io page) produces a
Statement of Work: model, samples, targets, endpoints, constraints. That is
where most tools stop. This module takes the SoW and *compiles it* to a concrete
plr-epigenome protocol + config that runs on the Hamilton STAR and carries a
validation tier. Planning is cheap; the value is the bridge to execution.

    sow = SoW.from_text(augmentiv_sow_text)
    run = compile_run(sow)         # picks the protocol, builds the config
    print(run.plan())              # what will run, on what, at what trust level
    report = await run.run()       # actually execute it (simulation by default)

Routing is deliberately transparent (keyword intent + light parsing), not a
black box, so a human can see and correct the mapping before anything runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .validation import PROTOCOL_STATUS

# Known antibody targets to lift out of free text.
_KNOWN_TARGETS = ["H3K27me3", "H3K27ac", "H3K4me3", "H3K9me3", "H3K36me3",
                  "CTCF", "RNAPII-Ser2P", "RNAPII", "Rad21", "Olig2", "IgG"]

# Protocol routing: first keyword group that matches wins. Order matters
# (more specific methods before the TIP-seq catch-all).
_ROUTES: List[Tuple[str, Tuple[str, ...]]] = [
    ("cut_and_tag",   ("cut&tag", "cut & tag", "cut and tag", "cutandtag", "cut_and_tag")),
    ("hydrop_atac",   ("hydrop", "scatac", "sc-atac", "atac", "droplet", "onyx")),
    ("normalization", ("normaliz", "normalis", "dsdna", "equimolar", "concentration balanc")),
    ("tipseq",        ("tip-seq", "tipseq", "targeted insertion of promoters", "cut&tag-ivt")),
]


@dataclass
class SoW:
    """A parsed Statement of Work. Fields map to a typical study intake."""

    title: str = ""
    model: str = ""
    samples: int = 0
    targets: Tuple[str, ...] = ()
    endpoints: str = ""
    timeline: str = ""
    constraints: str = ""
    raw: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "SoW":
        return cls(
            title=d.get("title", ""),
            model=d.get("model", d.get("sample_type", "")),
            samples=int(d.get("samples", 0) or 0),
            targets=tuple(d.get("targets", ()) or ()),
            endpoints=d.get("endpoints", ""),
            timeline=d.get("timeline", ""),
            constraints=d.get("constraints", ""),
            raw=d.get("raw", " ".join(str(v) for v in d.values())),
        )

    @classmethod
    def from_text(cls, text: str) -> "SoW":
        """Light parser for free-text SoWs (what an AI intake spits out)."""
        low = text.lower()
        # sample count: first "<N> samples" / "<N>-well" / "<N> wells"
        m = re.search(r"(\d{1,4})\s*(?:-?\s*well|samples|wells|reactions)", low)
        samples = int(m.group(1)) if m else 0
        matched = [t for t in _KNOWN_TARGETS if t.lower() in low]
        # drop a target that is a substring of a longer matched one (RNAPII vs RNAPII-Ser2P)
        targets = tuple(t for t in matched
                        if not any(o != t and t.lower() in o.lower() for o in matched))
        return cls(title=text.strip().split("\n", 1)[0][:120], samples=samples,
                   targets=targets, raw=text)

    def searchable(self) -> str:
        return " ".join([self.title, self.raw, " ".join(self.targets)]).lower()


@dataclass
class CompiledRun:
    protocol: str                  # "tipseq" | "cut_and_tag" | "normalization" | "hydrop_atac"
    method: Optional[str]          # tipseq variant (plate/bulk/sci) or None
    config: object                 # the ready-to-run config object
    sow: SoW
    notes: List[str] = field(default_factory=list)

    def validation_tier(self) -> str:
        tier = PROTOCOL_STATUS.get(self.protocol, {}).get("tier")
        return tier.value if hasattr(tier, "value") else str(tier or "untested")

    def cli(self) -> str:
        base = f"python -m tipseq_plr.protocols.{self.protocol}.run"
        if self.protocol == "tipseq" and self.method:
            base += f" --method {self.method}"
        return base + f" --samples {getattr(self.config, 'num_samples', '')}"

    def plan(self) -> dict:
        return {
            "sow_title": self.sow.title,
            "routed_to": self.protocol,
            "method": self.method,
            "samples": getattr(self.config, "num_samples", None),
            "targets": list(getattr(self.config, "antibody_targets", self.sow.targets)),
            "validation_tier": self.validation_tier(),
            "executable": True,
            "cli": self.cli(),
            "notes": self.notes,
        }

    async def run(self):
        """Execute the compiled protocol (simulation by default)."""
        setattr(self.config, "_sim_time_scale", getattr(self.config, "_sim_time_scale", 0.0))
        proto = self._make()
        return await proto.run()

    def _make(self):
        if self.protocol == "tipseq":
            from .protocols.tipseq import TipSeqProtocol
            return TipSeqProtocol(self.config)
        if self.protocol == "cut_and_tag":
            from .protocols.cut_and_tag import CutAndTag
            return CutAndTag(self.config)
        if self.protocol == "normalization":
            from .protocols.normalization import PlateNormalization
            return PlateNormalization(self.config)
        if self.protocol == "hydrop_atac":
            from .protocols.hydrop_atac import HyDropATAC
            return HyDropATAC(self.config)
        raise ValueError(f"unknown protocol {self.protocol}")


def route(sow: SoW) -> str:
    text = sow.searchable()
    for name, keywords in _ROUTES:
        if any(k in text for k in keywords):
            return name
    return "tipseq"        # default: the flagship epigenomic prep


def compile_run(sow: SoW, simulate: bool = True) -> CompiledRun:
    """Pick the protocol and build a ready-to-run config from the SoW."""
    protocol = route(sow)
    notes: List[str] = []
    text = sow.searchable()
    samples = sow.samples or (8 if protocol == "hydrop_atac" else 96)
    if not sow.samples:
        notes.append(f"sample count not stated; defaulted to {samples}")
    targets = sow.targets or _default_targets(protocol)

    method = None
    if protocol == "tipseq":
        from .config import RunConfig, Method
        sci = any(k in text for k in ("sci", "combinatorial", "facs", "single-cell index"))
        method = (Method.SCITIP_SEQ if sci else Method.PLATE_TIPSEQ)
        if sci:
            notes.append("single-cell indexing detected; routed to sciTIP-seq (FACS boundary applies)")
        config = RunConfig(method=method, num_samples=samples,
                           antibody_targets=tuple(targets), simulate=simulate)
        method = method.value
    elif protocol == "cut_and_tag":
        from .protocols.cut_and_tag import CutAndTagConfig
        config = CutAndTagConfig(num_samples=samples, antibody_targets=tuple(targets),
                                 simulate=simulate)
    elif protocol == "normalization":
        from .protocols.normalization import NormConfig
        config = NormConfig(num_samples=samples, simulate=simulate)
    elif protocol == "hydrop_atac":
        from .protocols.hydrop_atac import HyDropConfig
        config = HyDropConfig(num_samples=samples, simulate=simulate)
    else:
        raise ValueError(protocol)

    return CompiledRun(protocol=protocol, method=method, config=config, sow=sow, notes=notes)


def _default_targets(protocol: str) -> Tuple[str, ...]:
    if protocol in ("tipseq", "cut_and_tag"):
        return ("H3K27me3", "H3K27ac", "H3K9me3", "CTCF", "RNAPII-Ser2P")
    return ()


# -- CLI ---------------------------------------------------------------------
def main(argv=None):
    import argparse
    import asyncio
    import json
    import sys

    p = argparse.ArgumentParser(description="Compile a Statement of Work to a STAR run")
    p.add_argument("action", choices=["plan", "run"], help="plan (compile only) or run (execute)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="SoW as JSON ({title,model,samples,targets,...}) or a .txt")
    src.add_argument("--text", help="SoW free text")
    a = p.parse_args(argv)

    if a.text is not None:
        sow = SoW.from_text(a.text)
    elif a.file.endswith(".json"):
        sow = SoW.from_dict(json.load(open(a.file)))
    else:
        sow = SoW.from_text(open(a.file).read())

    run = compile_run(sow)
    print(json.dumps(run.plan(), indent=2))
    if a.action == "run":
        report = asyncio.run(run.run())
        print("\n=== run report ===")
        print(json.dumps(report.get("counts", report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
