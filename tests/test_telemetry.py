"""
Unit & Integration Test Suite for Telemetry Ingestion and Dataset Certification Engine.
"""
import pytest
from src.models.types import DatasetQualityVerdict, AnomalyType
from src.telemetry.stream import ZeroLossBuffer, TokyoTelemetrySimulator
from src.validation.detector import AnomalyDetector, DistributionDriftDetector
from src.telemetry.sink import TelemetryIngestPipeline, DatasetSink


def test_zero_loss_buffer_sequence_and_drops():
    buf = ZeroLossBuffer(capacity=100)
    sim = TokyoTelemetrySimulator()
    
    # Push 5 consecutive frames
    for _ in range(5):
        frame = sim.generate_frame()
        success, dropped = buf.push(frame)
        assert success is True
        assert dropped == 0
    assert buf.size == 5

    # Push frame skipping 3 frames
    skip_frame = sim.generate_frame(skip_sequence=3)
    success, dropped = buf.push(skip_frame)
    assert success is True
    assert dropped == 3
    assert buf.total_dropped_frames == 3


def test_imu_saturation_detection():
    detector = AnomalyDetector()
    sim = TokyoTelemetrySimulator()
    frame = sim.generate_frame(inject_imu_saturation=True)
    anomalies = detector.inspect_frame(frame)
    assert len(anomalies) >= 1
    assert any(a.anomaly_type == AnomalyType.IMU_SATURATION for a in anomalies)
    assert anomalies[0].severity == "CRITICAL"


def test_gps_multipath_teleportation():
    detector = AnomalyDetector()
    sim = TokyoTelemetrySimulator()
    f1 = sim.generate_frame()
    detector.inspect_frame(f1)
    
    f2 = sim.generate_frame(inject_gps_jump=True)
    anomalies = detector.inspect_frame(f2)
    assert len(anomalies) >= 1
    assert any(a.anomaly_type == AnomalyType.GPS_MULTIPATH_JUMP for a in anomalies)


def test_kinematic_violation():
    detector = AnomalyDetector()
    sim = TokyoTelemetrySimulator()
    frame = sim.generate_frame(inject_kinematic_violation=True)
    anomalies = detector.inspect_frame(frame)
    assert len(anomalies) >= 1
    assert any(a.anomaly_type == AnomalyType.KINEMATIC_VIOLATION for a in anomalies)


def test_distribution_drift_computation():
    drift_calc = DistributionDriftDetector(baseline_mean_speed=16.67, baseline_std_speed=3.0)
    sim = TokyoTelemetrySimulator()
    frames = [sim.generate_frame() for _ in range(30)]
    
    # Baseline run should have low drift
    score, anomaly = drift_calc.compute_drift(frames)
    assert score < 1.0
    assert anomaly is None

    # Alter speeds to simulate high-speed rain/highway drift
    for f in frames:
        f.speed_mps = 35.0
    drift_score, anomaly = drift_calc.compute_drift(frames)
    assert drift_score > 2.5
    assert anomaly is not None
    assert anomaly.anomaly_type == AnomalyType.DISTRIBUTION_DRIFT


def test_dataset_checksum_determinism():
    sim1 = TokyoTelemetrySimulator()
    sim2 = TokyoTelemetrySimulator()
    f1 = [sim1.generate_frame() for _ in range(25)]
    f2 = [sim2.generate_frame() for _ in range(25)]

    sink1 = DatasetSink()
    sink2 = DatasetSink()
    for frame in f1: sink1.sink_frame(frame)
    for frame in f2: sink2.sink_frame(frame)

    assert sink1.checksum == sink2.checksum
    assert len(sink1.checksum) == 64


def test_end_to_end_clean_pipeline_certified():
    pipeline = TelemetryIngestPipeline()
    sim = TokyoTelemetrySimulator()
    frames = [sim.generate_frame() for _ in range(50)]
    report = pipeline.process_stream(frames, "test-clean-dataset")
    assert report.verdict == DatasetQualityVerdict.CERTIFIED
    assert report.clean_frames_sunk == 50
    assert report.dropped_frames_count == 0
    assert len(report.anomalies) == 0
