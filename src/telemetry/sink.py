"""
Dataset Sink, Checksum Certification, and Telemetry Ingestion Pipeline.
"""
import hashlib
import json
import time
from typing import Dict, List, Optional
from src.models.types import (
    AnomalyEvent,
    DatasetQualityVerdict,
    IngestReport,
    VehicleTelemetryFrame,
)
from src.telemetry.stream import ZeroLossBuffer
from src.validation.detector import AnomalyDetector, DistributionDriftDetector


class DatasetSink:
    """
    Simulates writing validated telemetry into partitioned columnar/training storage with checksum verification.
    """
    def __init__(self):
        self._sunk_frames: List[VehicleTelemetryFrame] = []
        self._sha256 = hashlib.sha256()

    def sink_frame(self, frame: VehicleTelemetryFrame):
        self._sunk_frames.append(frame)
        serialized = f"{frame.frame_id}:{frame.timestamp_ns}:{frame.speed_mps:.3f}:{frame.accel_x:.3f}"
        self._sha256.update(serialized.encode("utf-8"))

    @property
    def total_sunk(self) -> int:
        return len(self._sunk_frames)

    @property
    def checksum(self) -> str:
        return self._sha256.hexdigest()


class TelemetryIngestPipeline:
    """
    End-to-end ingestion pipeline evaluating raw vehicle telemetry into a certified training dataset.
    """
    def __init__(
        self,
        buffer_capacity: int = 10000,
        anomaly_detector: Optional[AnomalyDetector] = None,
        drift_detector: Optional[DistributionDriftDetector] = None,
    ):
        self.buffer = ZeroLossBuffer(capacity=buffer_capacity)
        self.anomaly_detector = anomaly_detector or AnomalyDetector()
        self.drift_detector = drift_detector or DistributionDriftDetector()
        self.sink = DatasetSink()

    def process_stream(self, frames: List[VehicleTelemetryFrame], dataset_id: str = "ds-tokyo-telemetry-01") -> IngestReport:
        start_time = time.perf_counter()
        total_dropped = 0
        detected_anomalies: List[AnomalyEvent] = []

        # 1. Stream into Zero-Loss Ring Buffer
        for frame in frames:
            _, dropped = self.buffer.push(frame)
            total_dropped += dropped

        # 2. Pop batches from buffer and evaluate
        processed_frames: List[VehicleTelemetryFrame] = []
        while self.buffer.size > 0:
            batch = self.buffer.pop_batch(batch_size=100)
            for frame in batch:
                anomalies = self.anomaly_detector.inspect_frame(frame)
                if anomalies:
                    detected_anomalies.extend(anomalies)
                else:
                    self.sink.sink_frame(frame)
                processed_frames.append(frame)

        # 3. Distributional Drift Analysis
        drift_score, drift_anomaly = self.drift_detector.compute_drift(processed_frames)
        if drift_anomaly:
            detected_anomalies.append(drift_anomaly)

        # 4. Formulate Quality Verdict
        critical_count = sum(1 for a in detected_anomalies if a.severity == "CRITICAL")
        high_count = sum(1 for a in detected_anomalies if a.severity == "HIGH")

        if critical_count > 0 or total_dropped > 5 or drift_score > 3.0:
            verdict = DatasetQualityVerdict.REJECTED
        elif high_count > 0 or len(detected_anomalies) > 0 or total_dropped > 0:
            verdict = DatasetQualityVerdict.WARNING
        else:
            verdict = DatasetQualityVerdict.CERTIFIED

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return IngestReport(
            dataset_id=dataset_id,
            total_frames_received=len(frames),
            clean_frames_sunk=self.sink.total_sunk,
            dropped_frames_count=total_dropped,
            anomalies=detected_anomalies,
            drift_score=round(drift_score, 3),
            verdict=verdict,
            dataset_checksum=self.sink.checksum,
            processing_time_ms=round(elapsed_ms, 2),
        )
