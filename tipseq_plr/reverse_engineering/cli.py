"""
CLI for the FACSMelody reverse-engineering playbook.

    # 1. find the link (unplug/replug the Melody and diff)
    python -m tipseq_plr.reverse_engineering.cli discover --tcp-host 10.0.0.5

    # 2. mine the Chorus workstation (run ON the Chorus PC)
    python -m tipseq_plr.reverse_engineering.cli chorus --root "C:/ProgramData/BD"

    # 3. write the target command list, then mark actions while capturing
    python -m tipseq_plr.reverse_engineering.cli seed --out protocol.json
    python -m tipseq_plr.reverse_engineering.cli mark --out marks.json

    # 4. correlate a capture to the marks and decode into the protocol map
    python -m tipseq_plr.reverse_engineering.cli decode \
        --capture cap.pcapng --marks marks.json --transport usb \
        --endpoint usb:0x1fbd:0x0002 --out protocol.json

    # 5. review coverage; dry-run a read-only command
    python -m tipseq_plr.reverse_engineering.cli coverage --protocol protocol.json
    python -m tipseq_plr.reverse_engineering.cli replay --protocol protocol.json \
        --command get_status         # dry-run unless --armed --live are BOTH set
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import capture as cap
from . import chorus_probe, correlate, decode, transport_discovery
from .model import ProtocolMap, Transport, seed_required
from .replay import ReplayClient


def _load_capture(path: str):
    if path.endswith((".pcap", ".pcapng")):
        return cap.from_pcap(path)
    if "chorus" in path.lower() or path.endswith((".log", ".trace")):
        return cap.from_chorus_log(path)
    return cap.from_hexdump(path)


def cmd_discover(a):
    eps = transport_discovery.discover(tcp_host=a.tcp_host)
    for e in eps:
        flag = "  <-- BD hint" if e.extra.get("bd_hint") else ""
        print(f"[{e.transport.value:6}] {e.address:24} {e.vendor} {e.product} {e.description}{flag}")
    if not eps:
        print("no endpoints found (install pyusb/pyserial, or pass --tcp-host).")


def cmd_chorus(a):
    f = chorus_probe.probe(extra_roots=a.root)
    print(f"roots searched : {f.searched_roots}")
    print(f"processes      : {len(f.processes)}")
    for p in f.processes[:10]:
        print("   ", p)
    print(f"listening ports: {f.listening_ports}")
    print(f"log files      : {len(f.log_files)}  db files: {len(f.db_files)}  "
          f"experiment files: {len(f.experiment_files)}")
    if f.log_files:
        print("--- candidate command/status log lines ---")
        for line in chorus_probe.grep_logs(f.log_files)[:40]:
            print("   ", line)


def cmd_seed(a):
    seed_required().to_json(a.out)
    print(f"wrote target command list -> {a.out}")


def cmd_mark(a):
    sess = correlate.CorrelationSession()
    print("Marking session. Perform ONE Chorus action, then type its label + Enter.")
    print("Labels to cover:", ", ".join(c for c in seed_required().commands))
    print("Empty line to finish.\n")
    try:
        while True:
            label = input("action label> ").strip()
            if not label:
                break
            sess.mark(label)
    except (EOFError, KeyboardInterrupt):
        pass
    sess.save(a.out)
    print(f"\nwrote {len(sess.marks)} marks -> {a.out}")


def cmd_decode(a):
    frames = _load_capture(a.capture)
    sess = correlate.CorrelationSession.load(a.marks)
    windows = sess.correlate(frames, pre=a.pre, post=a.post, offset=a.offset)
    unique = sess.unique_frames(windows)
    base = ProtocolMap.from_json(a.base) if a.base else seed_required()
    pm = decode.assemble_protocol(unique, Transport(a.transport), a.endpoint, base=base)
    pm.to_json(a.out)
    cov = pm.coverage()
    print(f"decoded {cov['decoded']}/{cov['total']} commands -> {a.out}")
    if cov["missing"]:
        print("still undecoded:", ", ".join(cov["missing"]))


def cmd_coverage(a):
    pm = ProtocolMap.from_json(a.protocol)
    cov = pm.coverage()
    print(f"{pm.device} via {pm.transport.value} @ {pm.endpoint}")
    print(f"decoded {cov['decoded']}/{cov['total']}")
    for name, c in pm.commands.items():
        mark = "OK " if c.decoded else "-- "
        print(f"  {mark}{name:15} {c.frame_template or '(undecoded)'}")


def cmd_replay(a):
    pm = ProtocolMap.from_json(a.protocol)
    c = pm.commands.get(a.command)
    if c is None or not c.frame_template:
        sys.exit(f"command '{a.command}' is not decoded in {a.protocol}")
    client = ReplayClient(pm.transport, pm.endpoint or a.endpoint,
                          armed=a.armed, allow_actuation=a.allow_actuation)
    try:
        client.send(a.command, c.frame_template, live=a.live)
    except PermissionError as e:
        print(f"refused (safety): {e}")
        print("re-run with --allow-actuation (and --armed --live) only with a human present.")
        return 2
    finally:
        client.close()


def build_parser():
    p = argparse.ArgumentParser(prog="melody-re", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="count", default=0)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover"); d.add_argument("--tcp-host", default=None); d.set_defaults(fn=cmd_discover)
    ch = sub.add_parser("chorus"); ch.add_argument("--root", nargs="*", default=None); ch.set_defaults(fn=cmd_chorus)
    se = sub.add_parser("seed"); se.add_argument("--out", default="protocol.json"); se.set_defaults(fn=cmd_seed)
    mk = sub.add_parser("mark"); mk.add_argument("--out", default="marks.json"); mk.set_defaults(fn=cmd_mark)

    de = sub.add_parser("decode")
    de.add_argument("--capture", required=True)
    de.add_argument("--marks", required=True)
    de.add_argument("--transport", choices=[t.value for t in Transport], default="usb")
    de.add_argument("--endpoint", default=None)
    de.add_argument("--base", default=None, help="existing protocol.json to fold into")
    de.add_argument("--pre", type=float, default=0.3)
    de.add_argument("--post", type=float, default=2.0)
    de.add_argument("--offset", type=float, default=0.0)
    de.add_argument("--out", default="protocol.json")
    de.set_defaults(fn=cmd_decode)

    co = sub.add_parser("coverage"); co.add_argument("--protocol", required=True); co.set_defaults(fn=cmd_coverage)

    rp = sub.add_parser("replay")
    rp.add_argument("--protocol", required=True)
    rp.add_argument("--command", required=True)
    rp.add_argument("--endpoint", default=None)
    rp.add_argument("--armed", action="store_true", help="actually open the link")
    rp.add_argument("--live", action="store_true", help="actually transmit (needs --armed)")
    rp.add_argument("--allow-actuation", action="store_true", help="permit fluidic/sort commands")
    rp.set_defaults(fn=cmd_replay)
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if not a.verbose else logging.DEBUG,
                        format="%(name)-20s %(levelname)-7s %(message)s")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
