"""
Stage 2 of the RE playbook: mine the OEM software's own layer.

Rick's highest-leverage trick on the Hamilton was not sniffing wires first - it
was reading Venus's *trace logs*, which already contain the firmware command
strings. The FACSMelody analog is **BD FACSChorus** on its Windows workstation:
before touching USB, harvest what Chorus already writes down -

  * its log / trace files (often contain command + status strings verbatim),
  * its local experiment database (gates, sort settings, worklists),
  * its listening localhost services (the UI may talk to a control daemon),

because any of those can be a cleaner, more stable hook than the wire protocol.

Run this ON the Chorus workstation. Everything degrades gracefully off-Windows
(returns empty) so the module still imports and tests run anywhere.
"""

from __future__ import annotations

import glob
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("melody.re.chorus")

# Common Chorus/BD install + data locations to search. Confirm against your box.
CHORUS_PATH_HINTS = [
    r"C:\Program Files\BD\FACSChorus",
    r"C:\Program Files (x86)\BD\FACSChorus",
    r"C:\ProgramData\BD",
    r"C:\ProgramData\BD\FACSChorus",
    os.path.expanduser("~/BD"),
]
LOG_GLOBS = ["**/*.log", "**/*.trace", "**/Logs/**/*", "**/log/**/*"]
DB_GLOBS = ["**/*.sqlite", "**/*.db", "**/*.fdb", "**/*.mdf", "**/*.bak", "**/*.pgsql"]
EXPERIMENT_GLOBS = ["**/*.xml", "**/*.json", "**/*.experiment", "**/*.exp", "**/*.cst"]


@dataclass
class ChorusFindings:
    processes: List[str] = field(default_factory=list)
    listening_ports: List[int] = field(default_factory=list)
    log_files: List[str] = field(default_factory=list)
    db_files: List[str] = field(default_factory=list)
    experiment_files: List[str] = field(default_factory=list)
    searched_roots: List[str] = field(default_factory=list)


def find_processes(name_contains=("chorus", "facs", "bd")) -> List[str]:
    try:
        import psutil
    except Exception:
        logger.info("psutil not available; skipping process scan.")
        return []
    hits = []
    for p in psutil.process_iter(attrs=["name", "exe", "cmdline"]):
        blob = " ".join(filter(None, [p.info.get("name") or "",
                                       p.info.get("exe") or "",
                                       " ".join(p.info.get("cmdline") or [])])).lower()
        if any(k in blob for k in name_contains):
            hits.append(blob[:200])
    return hits


def find_listening_ports() -> List[int]:
    try:
        import psutil
    except Exception:
        return []
    ports = set()
    for c in psutil.net_connections(kind="inet"):
        if c.status == psutil.CONN_LISTEN and c.laddr:
            ports.add(c.laddr.port)
    return sorted(ports)


def _scan(roots: List[str], patterns: List[str], limit=500) -> List[str]:
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for pat in patterns:
            for path in glob.iglob(os.path.join(root, pat), recursive=True):
                if os.path.isfile(path):
                    found.append(path)
                    if len(found) >= limit:
                        return found
    return found


def probe(extra_roots: Optional[List[str]] = None) -> ChorusFindings:
    roots = [r for r in CHORUS_PATH_HINTS if os.path.isdir(r)]
    if extra_roots:
        roots += [r for r in extra_roots if os.path.isdir(r)]
    f = ChorusFindings(searched_roots=roots)
    f.processes = find_processes()
    f.listening_ports = find_listening_ports()
    f.log_files = _scan(roots, LOG_GLOBS)
    f.db_files = _scan(roots, DB_GLOBS)
    f.experiment_files = _scan(roots, EXPERIMENT_GLOBS)
    logger.info("Chorus probe: %d logs, %d dbs, %d experiment files across %d roots",
                len(f.log_files), len(f.db_files), len(f.experiment_files), len(roots))
    return f


def grep_logs(log_files: List[str], needles=("sort", "command", "deposit", "gate",
                                             "error", "clog", "nozzle", "->", "TX", "RX"),
              max_lines_per_file=2000) -> List[str]:
    """Pull candidate command/status lines out of Chorus logs. These are gold:
    the OEM software often prints the exact strings it sends/receives."""
    hits = []
    for path in log_files:
        try:
            with open(path, "r", errors="ignore") as fh:
                for i, line in enumerate(fh):
                    if i > max_lines_per_file:
                        break
                    low = line.lower()
                    if any(n.lower() in low for n in needles):
                        hits.append(f"{os.path.basename(path)}: {line.rstrip()}")
        except Exception as e:
            logger.debug("cannot read %s: %s", path, e)
    return hits
