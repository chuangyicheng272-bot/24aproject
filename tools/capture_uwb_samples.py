import argparse
import csv
import re
import statistics
import time
from pathlib import Path

import serial


RANGE_RE = re.compile(
    r"AT\+RANGE=tid:(?P<tag>\d+),mask:[0-9A-Fa-f]+,seq:(?P<seq>\d+),"
    r"range:\((?P<ranges>[^)]*)\),ancid:\((?P<anchors>[^)]*)\)"
)


def main():
    parser = argparse.ArgumentParser(description="Capture MaUWB range samples")
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument(
        "--output",
        default=str(
            Path(__file__).resolve().parents[1]
            / "data" / "measurements"
            / time.strftime("uwb_samples_%Y%m%d_%H%M%S.csv")
        ),
    )
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    samples = []
    deadline = time.monotonic() + args.timeout
    with serial.Serial(args.port, args.baud, timeout=1) as device:
        while len(samples) < args.count and time.monotonic() < deadline:
            line = device.readline().decode("utf-8", errors="ignore").strip()
            match = RANGE_RE.search(line)
            if not match:
                continue
            ranges = [int(value.strip()) for value in match.group("ranges").split(",")]
            anchors = [int(value.strip()) for value in match.group("anchors").split(",")]
            by_anchor = {anchor: ranges[index] * 10 for index, anchor in enumerate(anchors) if anchor > 0}
            if not all(anchor in by_anchor for anchor in (1, 2, 3, 4)):
                continue
            row = {
                "sample": len(samples) + 1,
                "sequence_id": int(match.group("seq")),
                "A1_mm": by_anchor[1],
                "A2_mm": by_anchor[2],
                "A3_mm": by_anchor[3],
                "A4_mm": by_anchor[4],
            }
            samples.append(row)
            print(
                f"{row['sample']:02d}/{args.count} seq={row['sequence_id']} "
                f"A1={row['A1_mm']} A2={row['A2_mm']} "
                f"A3={row['A3_mm']} A4={row['A4_mm']} mm",
                flush=True,
            )

    if len(samples) < args.count:
        raise SystemExit(f"Only captured {len(samples)}/{args.count} complete samples")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=samples[0].keys())
        writer.writeheader()
        writer.writerows(samples)

    print(f"Saved: {output.resolve()}")
    for anchor in range(1, 5):
        values = [row[f"A{anchor}_mm"] for row in samples]
        print(
            f"A{anchor}: mean={statistics.mean(values):.1f} mm, "
            f"min={min(values)}, max={max(values)}, "
            f"range={max(values) - min(values)}, stdev={statistics.pstdev(values):.1f} mm"
        )


if __name__ == "__main__":
    main()
