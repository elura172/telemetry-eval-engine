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


def test_buffer_applies_backpressure_without_overwrite_and_rejects_stale_frames():
    sim = TokyoTelemetrySimulator()
    buf = ZeroLossBuffer(capacity=2)
    first, second, third = [sim.generate_frame() for _ in range(3)]
    assert buf.push(first) == (True, 0)
    assert buf.push(second) == (True, 0)
    assert buf.push(third) == (False, 0)
    assert [f.frame_id for f in buf.pop_batch(2)] == [first.frame_id, second.frame_id]
    assert buf.push(third) == (True, 0)
    assert buf.push(second) == (False, 0)


def test_pipeline_rejects_duplicate_frame_ids():
    frame = TokyoTelemetrySimulator().generate_frame()
    report = TelemetryIngestPipeline().process_stream([frame, frame.model_copy()])
    assert report.verdict == DatasetQualityVerdict.REJECTED
    assert any(a.anomaly_type == AnomalyType.DROPPED_FRAME for a in report.anomalies)


def test_pipeline_does_not_lose_frames_when_input_exceeds_buffer_capacity():
    sim = TokyoTelemetrySimulator()
    frames = [sim.generate_frame() for _ in range(25)]
    report = TelemetryIngestPipeline(buffer_capacity=3).process_stream(frames)
    assert report.total_frames_received == 25
    assert report.clean_frames_sunk == 25
    assert report.dropped_frames_count == 0


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


def test_longitudinal_kinematic_limit_is_enforced():
    sim = TokyoTelemetrySimulator()
    frame = sim.generate_frame().model_copy(update={"accel_x": 13.0})
    anomalies = AnomalyDetector().inspect_frame(frame)
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


def test_dataset_checksum_covers_all_fields_and_canonicalizes_metadata():
    frame = TokyoTelemetrySimulator().generate_frame()
    changed = frame.model_copy(update={"imu_yaw_rate": frame.imu_yaw_rate + 0.01})
    reordered = frame.model_copy(update={"metadata": {"z": "last", "a": "first"}})
    reordered_same = reordered.model_copy(update={"metadata": {"a": "first", "z": "last"}})
    sink_a, sink_b, sink_c, sink_d = DatasetSink(), DatasetSink(), DatasetSink(), DatasetSink()
    sink_a.sink_frame(frame)
    sink_b.sink_frame(changed)
    sink_c.sink_frame(reordered)
    sink_d.sink_frame(reordered_same)
    assert sink_a.checksum != sink_b.checksum
    assert sink_c.checksum == sink_d.checksum


def test_pipeline_reuse_starts_a_fresh_dataset():
    pipeline = TelemetryIngestPipeline()
    sim = TokyoTelemetrySimulator()
    frames = [sim.generate_frame() for _ in range(5)]
    first = pipeline.process_stream(frames, "first")
    second = pipeline.process_stream(frames, "second")
    assert first.clean_frames_sunk == second.clean_frames_sunk == 5
    assert first.dataset_checksum == second.dataset_checksum


def test_frame_schema_rejects_invalid_geographic_and_nonfinite_values():
    frame = TokyoTelemetrySimulator().generate_frame()
    with pytest.raises(ValueError):
        frame.__class__.model_validate({**frame.model_dump(), "gps_lat": 91.0})
    with pytest.raises(ValueError):
        frame.__class__.model_validate({**frame.model_dump(), "accel_x": float("nan")})


def test_benchmark_suite_reports_each_scenario_verdict_correctly():
    from src.evals.harness import TelemetryBenchmarkSuite
    result = TelemetryBenchmarkSuite().run_benchmark()
    assert result["passed"] == result["total_scenarios"] == 10
    assert result["pass_rate_pct"] == 100.0
    scenario_3 = result["scenarios"][2]
    assert scenario_3["actual_verdict"] == scenario_3["expected_verdict"] == "REJECTED"
    scenario_8 = result["scenarios"][7]
    assert scenario_8["actual_verdict"] == scenario_8["expected_verdict"] == "WARNING"


def test_end_to_end_clean_pipeline_certified():
    pipeline = TelemetryIngestPipeline()
    sim = TokyoTelemetrySimulator()
    frames = [sim.generate_frame() for _ in range(50)]
    report = pipeline.process_stream(frames, "test-clean-dataset")
    assert report.verdict == DatasetQualityVerdict.CERTIFIED
    assert report.clean_frames_sunk == 50
    assert report.dropped_frames_count == 0
    assert len(report.anomalies) == 0
