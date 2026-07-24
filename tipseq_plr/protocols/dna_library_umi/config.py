"""
Configuration for a generic UMI library-workflow orchestrator.

This module intentionally contains no production chemistry recipe. A live run
must receive an operator-reviewed method mapping with every volume, duration,
ratio, thermal step, QC gate, and pooling target stated explicitly.

`synthetic_demo_method()` is the only bundled method. Its arbitrary numbers are
for exercising control flow in simulation; the resulting profile is rejected
before device construction if `simulate=False`.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple, Union

from ...config import QCThresholds


class MethodConfigError(ValueError):
    """An operator method is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class ThermalHold:
    celsius: float
    seconds: int
    name: str


@dataclass(frozen=True)
class EndPrep:
    input_ul: float
    buffer_ul: float
    enzyme_ul: float
    thermal_steps: Tuple[ThermalHold, ...]
    lid_c: float

    @property
    def total_ul(self) -> float:
        return self.input_ul + self.buffer_ul + self.enzyme_ul


@dataclass(frozen=True)
class Ligation:
    adaptor_ul: float
    master_mix_ul: float
    enhancer_ul: float
    incubation: ThermalHold
    lid_c: float
    mix_cycles: int
    adaptor_preparation: str

    def total_ul(self, incoming_ul: float) -> float:
        return incoming_ul + self.adaptor_ul + self.master_mix_ul + self.enhancer_ul


@dataclass(frozen=True)
class Cleanup:
    bead_ratio: float
    elution_ul: float
    transfer_ul: float
    ethanol_washes: int
    ethanol_ul: float


@dataclass(frozen=True)
class SizeSelection:
    """Explicit two-sided selection; there is deliberately no insert-size table."""

    first_bead_ul: float
    second_bead_ul: float
    first_magnet_settle_s: int
    second_magnet_settle_s: int
    ethanol_soak_s: int
    final_clear_settle_s: int
    elution_ul: float
    transfer_ul: float
    ethanol_washes: int
    ethanol_ul: float


@dataclass(frozen=True)
class PCR:
    primer_mix_ul: float
    master_mix_ul: float
    initial_denature: ThermalHold
    denature: ThermalHold
    anneal_extend: ThermalHold
    final_extend: ThermalHold
    cycles: int
    hold_c: float
    lid_c: float

    def total_ul(self, incoming_ul: float) -> float:
        return incoming_ul + self.primer_mix_ul + self.master_mix_ul


@dataclass(frozen=True)
class CleanupTimings:
    """Method-owned bead timings consumed by the shared liquid-operation layer."""

    bead_bind: int
    bead_dry: int


@dataclass(frozen=True)
class Pooling:
    target_ng_per_ul: float
    final_volume_ul: float


@dataclass(frozen=True)
class DnaLibraryMethod:
    profile_id: str
    endprep: EndPrep
    ligation: Ligation
    cleanup: Cleanup
    size_selection: Optional[SizeSelection]
    pcr: PCR
    pcr_cleanup: Cleanup
    timings: CleanupTimings
    qc: QCThresholds
    pooling: Pooling
    synthetic_only: bool


@dataclass
class DnaLibraryConfig:
    """Runtime/device choices plus one explicit chemistry method."""

    method: DnaLibraryMethod
    num_samples: int = 96
    simulate: bool = True

    # In-process CV error handling at reader-blind steps.
    vision_enabled: bool = False
    vision_abort_on_fault: bool = True
    vision_fault_at: tuple = ()

    # Device addressing (only used when simulate=False).
    star_id: str = "STAR"
    odtc_host: str = "192.168.1.50"
    odtc_port: int = 8080
    tecan_host: str = "192.168.1.60"

    def __post_init__(self):
        if not 1 <= self.num_samples <= 96:
            raise MethodConfigError("num_samples must be between 1 and 96")
        if not self.simulate and self.method.synthetic_only:
            raise MethodConfigError(
                "The bundled synthetic demo method cannot be used for a live run; "
                "supply an operator-reviewed method configuration."
            )

    # Compatibility properties keep the generic orchestrator and shared
    # LiquidOps API narrow without reintroducing chemistry defaults.
    @property
    def endprep(self) -> EndPrep:
        return self.method.endprep

    @property
    def ligation(self) -> Ligation:
        return self.method.ligation

    @property
    def cleanup(self) -> Cleanup:
        return self.method.cleanup

    @property
    def sizeselect(self) -> Optional[SizeSelection]:
        return self.method.size_selection

    @property
    def size_select(self) -> bool:
        return self.method.size_selection is not None

    @property
    def pcr(self) -> PCR:
        return self.method.pcr

    @property
    def pcr_cleanup(self) -> Cleanup:
        return self.method.pcr_cleanup

    @property
    def timings(self) -> CleanupTimings:
        return self.method.timings

    @property
    def qc(self) -> QCThresholds:
        return self.method.qc

    @property
    def pooling(self) -> Pooling:
        return self.method.pooling

    def cycles(self) -> int:
        return self.method.pcr.cycles


def load_operator_method(path: Union[str, Path]) -> DnaLibraryMethod:
    """Load a strict JSON method file. No bundled file contains live values."""

    source = Path(path)
    try:
        raw = json.loads(source.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise MethodConfigError(f"Cannot load operator method {source}: {exc}") from exc
    return operator_method_from_mapping(raw)


def operator_method_from_mapping(raw: Mapping[str, Any]) -> DnaLibraryMethod:
    """Build and validate a live-capable method from explicit operator data."""

    root = _mapping(raw, "method")
    _keys(
        root,
        {
            "profile_id",
            "endprep",
            "ligation",
            "cleanup",
            "size_selection",
            "pcr",
            "pcr_cleanup",
            "timings",
            "qc",
            "pooling",
        },
        "method",
    )

    ep = _mapping(root["endprep"], "endprep")
    _keys(ep, {"input_ul", "buffer_ul", "enzyme_ul", "thermal_steps", "lid_c"}, "endprep")
    thermal_raw = ep["thermal_steps"]
    if not isinstance(thermal_raw, list) or not thermal_raw:
        raise MethodConfigError("endprep.thermal_steps must be a non-empty list")
    endprep = EndPrep(
        input_ul=_positive(ep["input_ul"], "endprep.input_ul"),
        buffer_ul=_positive(ep["buffer_ul"], "endprep.buffer_ul"),
        enzyme_ul=_positive(ep["enzyme_ul"], "endprep.enzyme_ul"),
        thermal_steps=tuple(
            _thermal(step, f"endprep.thermal_steps[{index}]")
            for index, step in enumerate(thermal_raw)
        ),
        lid_c=_nonnegative(ep["lid_c"], "endprep.lid_c"),
    )

    lg = _mapping(root["ligation"], "ligation")
    _keys(
        lg,
        {
            "adaptor_ul",
            "master_mix_ul",
            "enhancer_ul",
            "incubation",
            "lid_c",
            "mix_cycles",
            "adaptor_preparation",
        },
        "ligation",
    )
    adaptor_preparation = lg["adaptor_preparation"]
    if not isinstance(adaptor_preparation, str) or not adaptor_preparation.strip():
        raise MethodConfigError("ligation.adaptor_preparation must be non-empty text")
    ligation = Ligation(
        adaptor_ul=_positive(lg["adaptor_ul"], "ligation.adaptor_ul"),
        master_mix_ul=_positive(lg["master_mix_ul"], "ligation.master_mix_ul"),
        enhancer_ul=_positive(lg["enhancer_ul"], "ligation.enhancer_ul"),
        incubation=_thermal(lg["incubation"], "ligation.incubation"),
        lid_c=_nonnegative(lg["lid_c"], "ligation.lid_c"),
        mix_cycles=_positive_int(lg["mix_cycles"], "ligation.mix_cycles"),
        adaptor_preparation=adaptor_preparation.strip(),
    )

    cleanup = _cleanup(root["cleanup"], "cleanup")
    size_selection = (
        None
        if root["size_selection"] is None
        else _size_selection(root["size_selection"], "size_selection")
    )
    pcr = _pcr(root["pcr"])
    pcr_cleanup = _cleanup(root["pcr_cleanup"], "pcr_cleanup")

    timings_raw = _mapping(root["timings"], "timings")
    _keys(timings_raw, {"bead_bind_s", "bead_dry_s"}, "timings")
    timings = CleanupTimings(
        bead_bind=_positive_int(timings_raw["bead_bind_s"], "timings.bead_bind_s"),
        bead_dry=_positive_int(timings_raw["bead_dry_s"], "timings.bead_dry_s"),
    )

    qc_raw = _mapping(root["qc"], "qc")
    _keys(
        qc_raw,
        {
            "min_library_ng_per_ul",
            "saturation_ng_per_ul",
            "standard_curve_ng",
            "excitation_nm",
            "emission_nm",
        },
        "qc",
    )
    standards_raw = qc_raw["standard_curve_ng"]
    if not isinstance(standards_raw, list) or len(standards_raw) != 8:
        raise MethodConfigError("qc.standard_curve_ng must contain exactly eight values")
    standards = tuple(
        _nonnegative(value, f"qc.standard_curve_ng[{index}]")
        for index, value in enumerate(standards_raw)
    )
    if any(b <= a for a, b in zip(standards, standards[1:])):
        raise MethodConfigError("qc.standard_curve_ng must be strictly increasing")
    min_qc = _nonnegative(qc_raw["min_library_ng_per_ul"], "qc.min_library_ng_per_ul")
    saturation = _positive(qc_raw["saturation_ng_per_ul"], "qc.saturation_ng_per_ul")
    if min_qc >= saturation:
        raise MethodConfigError("qc minimum must be below qc saturation")
    qc = QCThresholds(
        min_library_ng_per_ul=min_qc,
        saturation_ng_per_ul=saturation,
        standard_curve_ng=standards,
        excitation_nm=_positive_int(qc_raw["excitation_nm"], "qc.excitation_nm"),
        emission_nm=_positive_int(qc_raw["emission_nm"], "qc.emission_nm"),
    )

    pooling_raw = _mapping(root["pooling"], "pooling")
    _keys(pooling_raw, {"target_ng_per_ul", "final_volume_ul"}, "pooling")
    pooling = Pooling(
        target_ng_per_ul=_positive(pooling_raw["target_ng_per_ul"], "pooling.target_ng_per_ul"),
        final_volume_ul=_positive(pooling_raw["final_volume_ul"], "pooling.final_volume_ul"),
    )

    profile_id = root["profile_id"]
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise MethodConfigError("profile_id must be non-empty text")

    method = DnaLibraryMethod(
        profile_id=profile_id.strip(),
        endprep=endprep,
        ligation=ligation,
        cleanup=cleanup,
        size_selection=size_selection,
        pcr=pcr,
        pcr_cleanup=pcr_cleanup,
        timings=timings,
        qc=qc,
        pooling=pooling,
        synthetic_only=False,
    )
    _validate_capacity(method)
    return method


def synthetic_demo_method(*, size_selection: bool = False) -> DnaLibraryMethod:
    """Return arbitrary simulation data that is structurally unlike a live SOP."""

    method = DnaLibraryMethod(
        profile_id="synthetic-control-flow-demo",
        endprep=EndPrep(
            input_ul=10.0,
            buffer_ul=1.0,
            enzyme_ul=1.0,
            thermal_steps=(ThermalHold(25.0, 1, "synthetic-hold"),),
            lid_c=25.0,
        ),
        ligation=Ligation(
            adaptor_ul=1.0,
            master_mix_ul=1.0,
            enhancer_ul=1.0,
            incubation=ThermalHold(25.0, 1, "synthetic-ligation"),
            lid_c=25.0,
            mix_cycles=2,
            adaptor_preparation="synthetic placeholder",
        ),
        cleanup=Cleanup(
            bead_ratio=1.0,
            elution_ul=10.0,
            transfer_ul=8.0,
            ethanol_washes=1,
            ethanol_ul=20.0,
        ),
        size_selection=(
            SizeSelection(
                first_bead_ul=4.0,
                second_bead_ul=3.0,
                first_magnet_settle_s=1,
                second_magnet_settle_s=1,
                ethanol_soak_s=1,
                final_clear_settle_s=1,
                elution_ul=10.0,
                transfer_ul=8.0,
                ethanol_washes=1,
                ethanol_ul=20.0,
            )
            if size_selection
            else None
        ),
        pcr=PCR(
            primer_mix_ul=1.0,
            master_mix_ul=2.0,
            initial_denature=ThermalHold(90.0, 1, "synthetic-initial"),
            denature=ThermalHold(90.0, 1, "synthetic-denature"),
            anneal_extend=ThermalHold(50.0, 1, "synthetic-anneal"),
            final_extend=ThermalHold(50.0, 1, "synthetic-final"),
            cycles=2,
            hold_c=20.0,
            lid_c=25.0,
        ),
        pcr_cleanup=Cleanup(
            bead_ratio=1.0,
            elution_ul=10.0,
            transfer_ul=8.0,
            ethanol_washes=1,
            ethanol_ul=20.0,
        ),
        timings=CleanupTimings(bead_bind=1, bead_dry=1),
        qc=QCThresholds(
            min_library_ng_per_ul=0.1,
            saturation_ng_per_ul=100.0,
            standard_curve_ng=(0.0, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0),
            excitation_nm=485,
            emission_nm=530,
        ),
        pooling=Pooling(target_ng_per_ul=1.0, final_volume_ul=10.0),
        synthetic_only=True,
    )
    _validate_capacity(method)
    return method


def _thermal(raw: Any, path: str) -> ThermalHold:
    item = _mapping(raw, path)
    _keys(item, {"celsius", "seconds", "name"}, path)
    name = item["name"]
    if not isinstance(name, str) or not name.strip():
        raise MethodConfigError(f"{path}.name must be non-empty text")
    return ThermalHold(
        celsius=_nonnegative(item["celsius"], f"{path}.celsius"),
        seconds=_positive_int(item["seconds"], f"{path}.seconds"),
        name=name.strip(),
    )


def _cleanup(raw: Any, path: str) -> Cleanup:
    item = _mapping(raw, path)
    _keys(
        item,
        {"bead_ratio", "elution_ul", "transfer_ul", "ethanol_washes", "ethanol_ul"},
        path,
    )
    cleanup = Cleanup(
        bead_ratio=_positive(item["bead_ratio"], f"{path}.bead_ratio"),
        elution_ul=_positive(item["elution_ul"], f"{path}.elution_ul"),
        transfer_ul=_positive(item["transfer_ul"], f"{path}.transfer_ul"),
        ethanol_washes=_positive_int(item["ethanol_washes"], f"{path}.ethanol_washes"),
        ethanol_ul=_positive(item["ethanol_ul"], f"{path}.ethanol_ul"),
    )
    if cleanup.transfer_ul > cleanup.elution_ul:
        raise MethodConfigError(f"{path}.transfer_ul cannot exceed elution_ul")
    return cleanup


def _size_selection(raw: Any, path: str) -> SizeSelection:
    item = _mapping(raw, path)
    _keys(
        item,
        {
            "first_bead_ul",
            "second_bead_ul",
            "first_magnet_settle_s",
            "second_magnet_settle_s",
            "ethanol_soak_s",
            "final_clear_settle_s",
            "elution_ul",
            "transfer_ul",
            "ethanol_washes",
            "ethanol_ul",
        },
        path,
    )
    selection = SizeSelection(
        first_bead_ul=_positive(item["first_bead_ul"], f"{path}.first_bead_ul"),
        second_bead_ul=_positive(item["second_bead_ul"], f"{path}.second_bead_ul"),
        first_magnet_settle_s=_positive_int(
            item["first_magnet_settle_s"], f"{path}.first_magnet_settle_s"),
        second_magnet_settle_s=_positive_int(
            item["second_magnet_settle_s"], f"{path}.second_magnet_settle_s"),
        ethanol_soak_s=_positive_int(
            item["ethanol_soak_s"], f"{path}.ethanol_soak_s"),
        final_clear_settle_s=_positive_int(
            item["final_clear_settle_s"], f"{path}.final_clear_settle_s"),
        elution_ul=_positive(item["elution_ul"], f"{path}.elution_ul"),
        transfer_ul=_positive(item["transfer_ul"], f"{path}.transfer_ul"),
        ethanol_washes=_positive_int(item["ethanol_washes"], f"{path}.ethanol_washes"),
        ethanol_ul=_positive(item["ethanol_ul"], f"{path}.ethanol_ul"),
    )
    if selection.transfer_ul > selection.elution_ul:
        raise MethodConfigError(f"{path}.transfer_ul cannot exceed elution_ul")
    return selection


def _pcr(raw: Any) -> PCR:
    item = _mapping(raw, "pcr")
    _keys(
        item,
        {
            "primer_mix_ul",
            "master_mix_ul",
            "initial_denature",
            "denature",
            "anneal_extend",
            "final_extend",
            "cycles",
            "hold_c",
            "lid_c",
        },
        "pcr",
    )
    return PCR(
        primer_mix_ul=_positive(item["primer_mix_ul"], "pcr.primer_mix_ul"),
        master_mix_ul=_positive(item["master_mix_ul"], "pcr.master_mix_ul"),
        initial_denature=_thermal(item["initial_denature"], "pcr.initial_denature"),
        denature=_thermal(item["denature"], "pcr.denature"),
        anneal_extend=_thermal(item["anneal_extend"], "pcr.anneal_extend"),
        final_extend=_thermal(item["final_extend"], "pcr.final_extend"),
        cycles=_positive_int(item["cycles"], "pcr.cycles"),
        hold_c=_nonnegative(item["hold_c"], "pcr.hold_c"),
        lid_c=_nonnegative(item["lid_c"], "pcr.lid_c"),
    )


def _validate_capacity(method: DnaLibraryMethod):
    ligation_total = method.ligation.total_ul(method.endprep.total_ul)
    if ligation_total > 300:
        raise MethodConfigError("post-ligation volume exceeds the generic 300 uL workflow capacity")
    pcr_total = method.pcr.total_ul(
        method.size_selection.transfer_ul
        if method.size_selection is not None
        else method.cleanup.transfer_ul
    )
    if pcr_total > 300:
        raise MethodConfigError("PCR volume exceeds the generic 300 uL workflow capacity")


def _mapping(raw: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise MethodConfigError(f"{path} must be an object")
    return raw


def _keys(raw: Mapping[str, Any], expected: set[str], path: str):
    missing = expected - set(raw)
    extra = set(raw) - expected
    if missing or extra:
        bits = []
        if missing:
            bits.append(f"missing {sorted(missing)}")
        if extra:
            bits.append(f"unknown {sorted(extra)}")
        raise MethodConfigError(f"{path}: " + "; ".join(bits))


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MethodConfigError(f"{path} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise MethodConfigError(f"{path} must be finite")
    return number


def _positive(value: Any, path: str) -> float:
    number = _number(value, path)
    if number <= 0:
        raise MethodConfigError(f"{path} must be greater than zero")
    return number


def _nonnegative(value: Any, path: str) -> float:
    number = _number(value, path)
    if number < 0:
        raise MethodConfigError(f"{path} cannot be negative")
    return number


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MethodConfigError(f"{path} must be a positive integer")
    return value
