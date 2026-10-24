"""Evaluate the longitudinal-acceleration gate on a small real NGSIM trace."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

from src.models.types import AnomalyEvent
from src.validation.detector import AnomalyDetector


DEFAULT_DATA = Path(__file__).resolve().parents[2] / "data" / "ngsim_vehicle_396_total_frames_1628_first600.csv"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FEET_TO_METERS = 0.3048
NGSIM_DATASET_URL = "https://data.transportation.gov/d/8ect-6jqj"


@dataclass(frozen=True)
class AccelerationSample:
    frame_id: int
    timestamp_ns: int
    accel_x_mps2: float


def load_samples(path: Path) -> List[AccelerationSample]:
    required = {"vehicle_id", "total_frames", "frame_id", "global_time", "v_acc"}
    samples: List[AccelerationSample] = []
    vehicle_keys: Set[tuple[str, str]] = set()
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"CSV must contain columns: {', '.join(sorted(required))}")
        for row in reader:
            vehicle_keys.add((row["vehicle_id"], row["total_frames"]))
            samples.append(
                AccelerationSample(
                    frame_id=int(row["frame_id"]),
                    timestamp_ns=int(row["global_time"]) * 1_000_000,
                    # FHWA publishes v_acc in ft/s^2; the detector thresholds use m/s^2.
                    accel_x_mps2=float(row["v_acc"]) * FEET_TO_METERS,
                )
            )
    if len(vehicle_keys) != 1:
        raise ValueError("Sample must contain exactly one (vehicle_id, total_frames) trajectory")
    if not samples:
        raise ValueError("Sample contains no trajectory records")
    if any(b.timestamp_ns - a.timestamp_ns != 100_000_000 for a, b in zip(samples, samples[1:])):
        raise ValueError("Sample timestamps must be contiguous at the documented 10 Hz rate")
    if any(b.frame_id != a.frame_id + 1 for a, b in zip(samples, samples[1:])):
        raise ValueError("Sample frame IDs must be contiguous")
    return samples


def run_gate(samples: List[AccelerationSample], edits: Optional[Dict[int, float]] = None) -> Set[int]:
    detector = AnomalyDetector()
    detected: Set[int] = set()
    edits = edits or {}
    for sample in samples:
        acceleration = edits.get(sample.frame_id, sample.accel_x_mps2)
        events: List[AnomalyEvent] = detector.inspect_longitudinal_acceleration(
            frame_id=sample.frame_id,
            timestamp_ns=sample.timestamp_ns,
            accel_x=acceleration,
        )
        if events:
            detected.add(sample.frame_id)
    return detected


def _rate(numerator: int, denominator: int) -> Optional[float]:
    return round(numerator / denominator, 6) if denominator else None


def evaluate(path: Path = DEFAULT_DATA, repeats: int = 1000) -> dict:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    samples = load_samples(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    baseline_detected = run_gate(samples)
    # The labels here are the exact rows modified by the deterministic injection protocol.
    # One edit crosses the current 12 m/s^2 limit; one remains below it to expose a blind spot.
    edits = {
        samples[100].frame_id: 13.0,
        samples[300].frame_id: 11.5,
    }
    injected_labels = set(edits)
    injected_detected = run_gate(samples, edits)
    true_positive = len(injected_labels & injected_detected)
    false_positive = len(injected_detected - injected_labels)
    false_negative = len(injected_labels - injected_detected)
    true_negative = len(samples) - true_positive - false_positive - false_negative

    start = time.perf_counter()
    for _ in range(repeats):
        run_gate(samples)
    elapsed = time.perf_counter() - start
    evaluated_records = len(samples) * repeats

    return {
        "dataset": {
            "name": "FHWA NGSIM vehicle trajectories and supporting data",
            "source_url": NGSIM_DATASET_URL,
            "license": "CC BY-SA 3.0",
            "sample_file": str(path.resolve().relative_to(REPOSITORY_ROOT))
            if path.resolve().is_relative_to(REPOSITORY_ROOT)
            else path.name,
            "sample_sha256": digest,
            "records": len(samples),
            "sample_rate_hz": 10,
            "vehicle_key": "vehicle_id=396,total_frames=1628",
            "units_conversion": "v_acc ft/s^2 to m/s^2 using 0.3048",
            "source_fault_labels_available": False,
        },
        "scope": {
            "evaluated_gate": "longitudinal acceleration plausibility",
            "configured_longitudinal_limit_mps2": 12.0,
            "evaluated_fields": ["frame_id", "timestamp_ns", "v_acc"],
            "excluded_checks": ["GPS", "IMU sensor-rail interpretation", "lateral acceleration", "camera sync", "distribution drift"],
            "labeling_note": "NGSIM has no sensor-fault labels. Confusion metrics use only the exact injected edits as positive labels and assume all unmodified rows are clean; this assumption is not source ground truth.",
        },
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "baseline": {
            "records": len(samples),
            "alarm_rows": len(baseline_detected),
            "alarm_frame_ids": sorted(baseline_detected),
        },
        "injected_faults": {
            "edits": [
                {"frame_id": frame_id, "accel_x_mps2": value, "label": "injected value edit"}
                for frame_id, value in edits.items()
            ],
            "true_positive_rows": true_positive,
            "false_positive_rows_on_unmodified_data": false_positive,
            "false_negative_rows": false_negative,
            "true_negative_rows_under_clean_trace_assumption": true_negative,
            "precision": _rate(true_positive, true_positive + false_positive),
            "recall": _rate(true_positive, true_positive + false_negative),
        },
        "throughput": {
            "repeats": repeats,
            "records_evaluated": evaluated_records,
            "elapsed_seconds": round(elapsed, 6),
            "records_per_second": round(evaluated_records / elapsed, 2) if elapsed else None,
            "measurement_scope": "detector gate only; excludes CSV parsing and file I/O",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--repeats", type=int, default=1000)
    parser.add_argument("--output", type=Path, help="optional path for the JSON report")
    args = parser.parse_args()
    report = evaluate(args.data, args.repeats)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
