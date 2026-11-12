"""CSV manifest appended to the output folder (legacy-compatible columns)."""

from __future__ import annotations

import csv
import os
import time

from .events import ProcessRecord

COLUMNS = ("file", "status", "regions", "seconds", "seed", "detections", "message", "time", "reused")
FILENAME = "_AnimeMosaicStudio_manifest.csv"
LEGACY_FILENAME = "_AutoMosaicStudio_manifest.csv"


class ManifestWriter:
    """Append-only processing log.  Failures are non-fatal by design."""

    def __init__(self, output_dir: str, filename: str = FILENAME):
        self.path = os.path.join(output_dir, filename)

    def append(self, record: ProcessRecord) -> None:
        new_file = not os.path.isfile(self.path)
        try:
            with open(self.path, "a", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                if new_file:
                    writer.writerow(COLUMNS)
                writer.writerow(
                    [
                        record.file,
                        record.status,
                        record.regions,
                        record.seconds,
                        record.seed,
                        record.detections,
                        record.message[:500],
                        time.strftime("%Y-%m-%d %H:%M:%S"),
                        "1" if record.reused else "0",
                    ]
                )
        except OSError:
            pass
