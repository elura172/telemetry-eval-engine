"""In-memory clean-frame sink, content checksum, and telemetry evaluation pipeline."""
import hashlib
import json
import time
from typing import List, Optional
from src.models.types import (
    AnomalyEvent,
    AnomalyType,
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
        # Canonical, framed serialization covers every schema field, including metadata.
        serialized = json.dumps(
            frame.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self._sha256.update(serialized.encode("utf-8"))
        self._sha256.update(b"\n")

    @property
    def total_sunk(self) -> int:
        return len(self._sunk_frames)

    @property
    def checksum(self) -> str:
        return self._sha256.hexdigest()


class TelemetryIngestPipeline:
    """
    In-memory evaluation pipeline that reports quality gates and hashes accepted frames.
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
        # A pipeline may be reused; each call evaluates one independent dataset.
        self.buffer = ZeroLossBuffer(capacity=self.buffer.capacity)
        self.anomaly_detector.reset()
        self.sink = DatasetSink()
        total_dropped = 0
        detected_anomalies: List[AnomalyEvent] = []
        processed_frames: List[VehicleTelemetryFrame] = []

        def drain_buffer() -> None:
            while self.buffer.size:
                for frame in self.buffer.pop_batch(batch_size=100):
                    anomalies = self.anomaly_detector.inspect_frame(frame)
                    detected_anomalies.extend(anomalies)
                    if not anomalies:
                        self.sink.sink_frame(frame)
                    processed_frames.append(frame)

        # Drain under backpressure instead of allowing the fixed-capacity buffer to lose frames.
        for frame in frames:
            if self.buffer.size == self.buffer.capacity:
                drain_buffer()
            accepted, dropped = self.buffer.push(frame)
            if not accepted:
                detected_anomalies.append(AnomalyEvent(
                    frame_id=frame.frame_id,
                    timestamp_ns=frame.timestamp_ns,
                    anomaly_type=AnomalyType.DROPPED_FRAME,
                    severity="CRITICAL",
                    description="Duplicate or out-of-order frame rejected by sequence guard",
                    metric_value=float(frame.frame_id),
                    threshold_value=float(self.buffer.last_frame_id or 0),
                ))
            total_dropped += dropped
        drain_buffer()

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
