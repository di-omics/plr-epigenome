"""
Stage 4 of the RE playbook: correlate one OEM action to its bytes.

This is the heart of Rick's method: you don't decode a firehose, you perform
*one discrete action* in Chorus ("click Start Sort"), mark the instant, and look
only at the bytes that appeared in that window. Do it for each action; diff the
windows to cancel out the periodic keep-alive/status chatter and leave the
command that is unique to that action.

Workflow:
    sess = CorrelationSession()
    # ... start Wireshark, then drive Chorus, calling mark() as you go ...
    sess.mark("start_sort")
    sess.mark("abort")
    sess.save("marks.json")
    frames = capture.from_pcap("cap.pcapng")
    windows = sess.correlate(frames)          # {label: [frames in its window]}
    unique  = sess.unique_frames(windows)     # {label: frames not seen elsewhere}
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from typing import Dict, List

from .model import ActionMark, CaptureFrame

logger = logging.getLogger("melody.re.correlate")


class CorrelationSession:
    def __init__(self, clock=time.time):
        self._clock = clock
        self.marks: List[ActionMark] = []

    def mark(self, label: str, note: str = "") -> ActionMark:
        m = ActionMark(ts=self._clock(), label=label, note=note)
        self.marks.append(m)
        logger.info("marked '%s' @ %.3f", label, m.ts)
        return m

    def save(self, path: str):
        with open(path, "w") as fh:
            json.dump([asdict(m) for m in self.marks], fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "CorrelationSession":
        sess = cls()
        with open(path) as fh:
            for d in json.load(fh):
                sess.marks.append(ActionMark(**d))
        return sess

    def window(self, frames: List[CaptureFrame], label: str,
               pre: float = 0.3, post: float = 2.0, offset: float = 0.0) -> List[CaptureFrame]:
        """Frames within [mark-pre, mark+post]. `offset` aligns the capture clock
        to the mark clock if they differ (capture_ts + offset ≈ mark_ts)."""
        marks = [m for m in self.marks if m.label == label]
        out = []
        for m in marks:
            lo, hi = m.ts - pre, m.ts + post
            out += [f for f in frames if lo <= (f.ts + offset) <= hi]
        return out

    def correlate(self, frames: List[CaptureFrame], pre: float = 0.3,
                  post: float = 2.0, offset: float = 0.0) -> Dict[str, List[CaptureFrame]]:
        return {m.label: self.window(frames, m.label, pre, post, offset)
                for m in self.marks}

    def unique_frames(self, windows: Dict[str, List[CaptureFrame]],
                      direction: str = "out") -> Dict[str, List[CaptureFrame]]:
        """Per label, the host->device frames whose bytes don't appear in any
        other label's window. Cancels keep-alive/status noise, leaving the
        action-specific command candidate(s)."""
        by_label_bytes = {
            label: {f.data for f in fr if f.direction == direction}
            for label, fr in windows.items()
        }
        result = {}
        for label, mine in by_label_bytes.items():
            others = set()
            for other_label, b in by_label_bytes.items():
                if other_label != label:
                    others |= b
            uniq = mine - others
            result[label] = [f for f in windows[label]
                             if f.direction == direction and f.data in uniq]
        return result
