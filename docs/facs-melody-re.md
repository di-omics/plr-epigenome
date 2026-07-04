# Reverse-engineering the BD FACSMelody to close the sciTIP-seq sort gap

The one step in sciTIP-seq a Hamilton STAR can't do is the **FACS re-distribution
of pooled index-1 cells into the index-2 plate**. This is the playbook for making
the [BD FACSMelody](https://www.bdbiosciences.com) drive that sort automatically,
so the pipeline runs closed-loop.

It applies the methodology **Rick Wierenga** used to build PyLabRobot's device
backends: don't invent a protocol - work down to the OEM's own command layer,
sniff the OEM↔device traffic, correlate each UI action to its bytes, decode the
framing, and replay with PyUSB/pyserial before wrapping it in a backend. (See
his talk *"How To Reverse Engineer Lab Equipment"* and the
[PyLabRobot paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10369895/), whose STAR
and EVO backends were built from OEM firmware command strings + captured traffic.)

The toolkit lives in [`tipseq_plr/reverse_engineering/`](../tipseq_plr/reverse_engineering).
Its deliverable is a **`ProtocolMap`** (a JSON of decoded commands); the runtime
[`BDFACSMelodyBackend`](../tipseq_plr/backends/bd_facsmelody.py) loads it and the
FACS step becomes a normal device call.

## What the sort actually has to do

Combinatorial indexing tolerates **25-100 cells per well** and does **not** need
index-sorting (recording which cell landed where). So the target is small:

1. a **fixed gate template** (FSC/SSC -> PI singlet) built once in Chorus,
2. **count-controlled deposition** into a 96-well plate,
3. programmatic **trigger + status polling + clean**.

That means we mostly need to reverse-engineer *how to trigger a saved template
and move plates* - not BD's gating math. The required command set is exactly
`REQUIRED_COMMANDS` in [`model.py`](../tipseq_plr/reverse_engineering/model.py):
`connect, get_status, load_template, set_deposition, prime, start_sort,
wait_complete, abort, clean`.

## Stage 1 - find the link (`discover`)

The Melody talks to the Chorus workstation over USB and/or an Ethernet cart link.
Enumerate everything, unplug/replug the instrument, and diff to isolate its link.

```bash
python -m tipseq_plr.reverse_engineering.cli discover --tcp-host <chorus-or-cart-ip>
```

`discover` lists USB (PyUSB), serial (pyserial) and open TCP control-port
candidates, flagging likely BD vendor IDs. Note the endpoint (e.g.
`usb:0x1fbd:0x0002`).

## Stage 2 - mine Chorus first (`chorus`)

Rick's highest-leverage move on the STAR wasn't the wire - it was **Venus's own
trace logs**, which print the firmware strings verbatim. The Melody analog is
**FACSChorus**. Run this **on the Chorus PC**:

```bash
python -m tipseq_plr.reverse_engineering.cli chorus --root "C:/ProgramData/BD" "C:/Program Files/BD"
```

It finds Chorus processes, listening localhost ports (the UI may talk to a local
control daemon - a cleaner hook than USB), log/trace files, the local experiment
**database**, and experiment files. It greps logs for command/status lines. If
Chorus logs the bytes or exposes a localhost service, you may not need to sniff
USB at all.

## Stage 3 - capture while you drive (Wireshark/USBPcap/usbmon)

Start your platform sniffer on the Melody's interface, then drive Chorus by hand.

- **Windows:** Wireshark + USBPcap on the USB interface -> export `.pcapng`.
- **Linux:** `usbmon` or Wireshark.
- **Serial:** a COM sniffer saved as `<ts> <dir> <hexbytes>` lines.

The toolkit *ingests* these - it doesn't reimplement a sniffer. Parsers:
`capture.from_pcap` (pyshark/scapy), `capture.from_hexdump` (no deps),
`capture.from_chorus_log`.

## Stage 4 - one action at a time (`mark` -> `decode`)

The core trick: perform **one discrete Chorus action**, mark the instant, and
look only at the bytes in that window. Diff windows to cancel the periodic
keep-alive/status chatter, leaving the command unique to each action.

```bash
# start the sniffer, then:
python -m tipseq_plr.reverse_engineering.cli mark --out marks.json
#   -> click "Start Sort" in Chorus, type: start_sort <Enter>
#   -> click "Abort",              type: abort       <Enter>
#   -> ... cover every REQUIRED command ... empty line to finish
```

Then correlate the capture to the marks and decode the framing (terminators,
opcode = common prefix, checksum brute-force) into the ProtocolMap:

```bash
python -m tipseq_plr.reverse_engineering.cli decode \
    --capture cap.pcapng --marks marks.json \
    --transport usb --endpoint usb:0x1fbd:0x0002 --out protocol.json
```

`decode` reports **coverage** - which required commands are decoded and which
still aren't. Parameters (cells/well, well count) are found by varying **one**
setting in Chorus and diffing the frames; wire their encoders into
`bd_facsmelody._encode_param`.

## Stage 5 - confirm safely (`replay`)

⚠️ The Melody is a laser + pressurized-fluidics instrument. Replay defaults are
deliberately timid - **two independent safety switches, both off by default**:

- `--armed` opens the link; without it, `replay` is pure dry-run (logs bytes).
- `--live` actually transmits; needs `--armed` too.
- fluidic/sort commands (`prime/start_sort/clean/set_deposition`) additionally
  require `--allow-actuation` and a human present.

Confirm the **read-only** command first:

```bash
python -m tipseq_plr.reverse_engineering.cli replay --protocol protocol.json \
    --command get_status            # dry-run
python -m tipseq_plr.reverse_engineering.cli replay --protocol protocol.json \
    --command get_status --armed --live     # actually query
```

Only once `get_status` round-trips cleanly do you touch actuating commands, with
BD service or your safety officer in the loop.

## Stage 6 - run it closed-loop

Point the pipeline at the decoded protocol:

```python
from tipseq_plr import RunConfig, Method, TipSeqProtocol
cfg = RunConfig(
    method=Method.SCITIP_SEQ, num_samples=96, simulate=False,
    sorter_enabled=True,
    sorter_protocol_path="protocol.json",
    sorter_armed=True, sorter_allow_actuation=True,   # live sort
    sort_cells_per_well=50,
)
```

Now `TipSeqProtocol._facs_handoff` drives `sort_to_plate` instead of raising -
the STAR pools index-1, hands the tube + index-2 plate to the Melody (via arm or
plate hotel), the sort runs, and the STAR resumes into IVT. `BDFACSMelodyBackend`
**refuses to start** if any required command is still undecoded, so a half-mapped
protocol can never drive live hardware.

## Physical bridge (still required)

Software control ≠ full autonomy. You still need to move a **sample tube onto the
SIP** and the **index-2 plate on/off the deposition stage** - a bench cobot (UR
or similar) or a shared plate hotel. And expose the sorter's **clog/error status**
as an interlock: a clogged nozzle silently ruins a plate.

## Decision gate

Reverse-engineering a closed BD sorter is real work. If the Melody isn't sacred,
an **API-controllable single-cell dispenser** (cellenONE, WOLF G2, Namocell Hana)
does the same job - doublet exclusion + count-controlled plate deposition - with
a documented interface and none of this RE. The orchestrator change is identical:
`sorter` becomes a different backend behind the same `sort_to_plate` call. Gate
the go/no-go after Stage 2, once you know how open Chorus really is.
