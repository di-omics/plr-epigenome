"""Tests for the HyDrop scATAC + Onyx + robot-arm workflow (no hardware)."""

import asyncio

from tipseq_plr.backends import DropletParams, OnyxBackend, RobotArmBackend, Site, VSpinBackend
from tipseq_plr.protocols.hydrop_atac import HyDropATAC, HyDropConfig


def _cfg(**kw):
    cfg = HyDropConfig(simulate=True, **kw)
    setattr(cfg, "_sim_time_scale", 0.0)
    return cfg


def test_end_to_end_simulation():
    report = asyncio.run(HyDropATAC(_cfg(num_samples=8)).run())
    assert report["samples"] == 8
    assert report["libraries"] == 8
    assert report["emulsion_ul"] > 0


def test_arm_and_onyx_are_wired_when_enabled():
    proto = HyDropATAC(_cfg(num_samples=8))
    assert proto.devices.arm is not None
    assert proto.devices.onyx is not None


def test_arm_transfer_tracks_holding():
    arm = RobotArmBackend(simulate=True)
    arm.register_site(Site("a", "star"))
    arm.register_site(Site("b", "onyx"))

    async def go():
        await arm.setup()
        await arm.transfer("chip", "a", "b")
        return arm._holding
    assert asyncio.run(go()) is None            # released after place


def test_arm_refuses_double_pick():
    arm = RobotArmBackend(simulate=True)
    arm.register_site(Site("a", "star"))

    async def go():
        await arm.setup()
        await arm.pick("a", "chip1")
        try:
            await arm.pick("a", "chip2")         # already holding chip1
            return "no-error"
        except RuntimeError:
            return "blocked"
    assert asyncio.run(go()) == "blocked"


def test_onyx_generate_reaches_target():
    onyx = OnyxBackend(simulate=True)

    async def go():
        await onyx.setup()
        return await onyx.run_hydrop(DropletParams(target_emulsion_ul=120.0))
    assert asyncio.run(go()) == 120.0


def test_live_arm_requires_enable():
    arm = RobotArmBackend(simulate=False, enabled=False)
    try:
        asyncio.run(arm.setup())
        raised = False
    except RuntimeError:
        raised = True
    assert raised


def test_low_n_and_multicolumn_shapes():
    for n in (1, 8, 16, 24):
        r = asyncio.run(HyDropATAC(_cfg(num_samples=n)).run())
        assert r["libraries"] == n


def test_vspin_present_by_default_absent_when_preconcentrated():
    assert HyDropATAC(_cfg(num_samples=8)).devices.centrifuge is not None
    assert HyDropATAC(_cfg(num_samples=8, nuclei_preconcentrated=True)).devices.centrifuge is None


def test_vspin_spins_in_sim():
    vs = VSpinBackend(simulate=True)

    async def go():
        await vs.setup()
        await vs.spin(500, 300, temperature_c=4.0)
        return True
    assert asyncio.run(go())


def test_vspin_refuses_unbalanced_live():
    vs = VSpinBackend(simulate=False, require_balance=True)
    # skip setup() (would need hardware); balance guard is independent
    raised = False
    try:
        asyncio.run(vs.spin(500, 300))
    except RuntimeError:
        raised = True
    assert raised
