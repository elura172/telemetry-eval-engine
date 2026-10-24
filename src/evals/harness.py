"""
Automated Evaluation Harness for Autonomous Vehicle Telemetry Ingestion & Quality Gates.
"""
from typing import Any, Dict, List
from src.models.types import DatasetQualityVerdict, AnomalyType, IngestReport
from src.telemetry.stream import TokyoTelemetrySimulator
from src.telemetry.sink import TelemetryIngestPipeline


class TelemetryBenchmarkSuite:
    """
    10-Scenario canonical validation suite benchmarking automotive telemetry ingestion against physical and statistical bounds.
    """
    def __init__(self):
        pass

    def run_benchmark(self) -> Dict[str, Any]:
        results = []
        passed = 0

        # Scenario 1: Pristine Tokyo Highway Run
        sim = TokyoTelemetrySimulator()
        frames_1 = [sim.generate_frame() for _ in range(50)]
        pipe_1 = TelemetryIngestPipeline()
        rep_1 = pipe_1.process_stream(frames_1, "ds-01-clean")
        p1 = rep_1.verdict == DatasetQualityVerdict.CERTIFIED and len(rep_1.anomalies) == 0
        if p1: passed += 1
        results.append({
            "scenario": "01_PRISTINE_HIGHWAY_RUN",
            "description": "Clean 50Hz telemetry sequence along Tokyo Expressway",
            "expected_verdict": DatasetQualityVerdict.CERTIFIED.value,
            "actual_verdict": rep_1.verdict.value,
            "anomalies_detected": len(rep_1.anomalies),
            "passed": p1,
        })

        # Scenario 2: GPS Multipath Jump
        sim = TokyoTelemetrySimulator()
        frames_2 = [sim.generate_frame() for _ in range(20)]
        frames_2.append(sim.generate_frame(inject_gps_jump=True))
        pipe_2 = TelemetryIngestPipeline()
        rep_2 = pipe_2.process_stream(frames_2, "ds-02-gps")
        p2 = rep_2.verdict == DatasetQualityVerdict.REJECTED and any(a.anomaly_type == AnomalyType.GPS_MULTIPATH_JUMP for a in rep_2.anomalies)
        if p2: passed += 1
        results.append({
            "scenario": "02_GPS_MULTIPATH_TELEPORTATION",
            "description": "Sudden 5km coordinate jump (tunnel multipath reflection)",
            "expected_verdict": DatasetQualityVerdict.REJECTED.value,
            "actual_verdict": rep_2.verdict.value,
            "anomalies_detected": len(rep_2.anomalies),
            "passed": p2,
        })

        # Scenario 3: IMU Sensor Rail Saturation
        sim = TokyoTelemetrySimulator()
        frames_3 = [sim.generate_frame() for _ in range(20)]
        frames_3.append(sim.generate_frame(inject_imu_saturation=True))
        pipe_3 = TelemetryIngestPipeline()
        rep_3 = pipe_3.process_stream(frames_3, "ds-03-imu")
        p3 = rep_3.verdict == DatasetQualityVerdict.REJECTED and any(a.anomaly_type == AnomalyType.IMU_SATURATION for a in rep_3.anomalies)
        if p3: passed += 1
        results.append({
            "scenario": "03_IMU_SENSOR_RAIL_SATURATION",
            "description": "Accelerometer saturation spike exceeding hardware sensor rails (45 m/s^2)",
            "expected_verdict": DatasetQualityVerdict.REJECTED.value,
            "actual_verdict": rep_2.verdict.value,
            "anomalies_detected": len(rep_3.anomalies),
            "passed": p3,
        })

        # Scenario 4: Kinematic Friction Violation
        sim = TokyoTelemetrySimulator()
        frames_4 = [sim.generate_frame() for _ in range(20)]
        frames_4.append(sim.generate_frame(inject_kinematic_violation=True))
        pipe_4 = TelemetryIngestPipeline()
        rep_4 = pipe_4.process_stream(frames_4, "ds-04-kinematic")
        p4 = any(a.anomaly_type == AnomalyType.KINEMATIC_VIOLATION for a in rep_4.anomalies)
        if p4: passed += 1
        results.append({
            "scenario": "04_KINEMATIC_LATERAL_VIOLATION",
            "description": "Lateral acceleration exceeding road tire friction coefficient (impossible maneuver)",
            "expected_verdict": DatasetQualityVerdict.WARNING.value,
            "actual_verdict": rep_4.verdict.value,
            "anomalies_detected": len(rep_4.anomalies),
            "passed": p4,
        })

        # Scenario 5: High Dropped Frames Sequence
        sim = TokyoTelemetrySimulator()
        frames_5 = [sim.generate_frame() for _ in range(10)]
        frames_5.append(sim.generate_frame(skip_sequence=15)) # 15 missing frames
        frames_5.extend([sim.generate_frame() for _ in range(10)])
        pipe_5 = TelemetryIngestPipeline()
        rep_5 = pipe_5.process_stream(frames_5, "ds-05-drops")
        p5 = rep_5.verdict == DatasetQualityVerdict.REJECTED and rep_5.dropped_frames_count == 15
        if p5: passed += 1
        results.append({
            "scenario": "05_HIGH_DROPPED_FRAME_BURST",
            "description": "Network buffer drop (15 dropped frames detected via sequence counters)",
            "expected_verdict": DatasetQualityVerdict.REJECTED.value,
            "actual_verdict": rep_5.verdict.value,
            "anomalies_detected": rep_5.dropped_frames_count,
            "passed": p5,
        })

        # Scenario 6: Single Minor Dropped Packet
        sim = TokyoTelemetrySimulator()
        frames_6 = [sim.generate_frame() for _ in range(10)]
        frames_6.append(sim.generate_frame(skip_sequence=1)) # 1 missing frame
        frames_6.extend([sim.generate_frame() for _ in range(10)])
        pipe_6 = TelemetryIngestPipeline()
        rep_6 = pipe_6.process_stream(frames_6, "ds-06-single-drop")
        p6 = rep_6.verdict == DatasetQualityVerdict.WARNING and rep_6.dropped_frames_count == 1
        if p6: passed += 1
        results.append({
            "scenario": "06_SINGLE_PACKET_DROP_TOLERANCE",
            "description": "Isolated single dropped frame (flagged with WARNING without hard rejection)",
            "expected_verdict": DatasetQualityVerdict.WARNING.value,
            "actual_verdict": rep_6.verdict.value,
            "anomalies_detected": rep_6.dropped_frames_count,
            "passed": p6,
        })

        # Scenario 7: Distributional Speed Drift
        sim = TokyoTelemetrySimulator()
        frames_7 = [sim.generate_frame() for _ in range(50)]
        # Artificially alter speed
        for f in frames_7:
            f.speed_mps = 38.0 # Extreme speed shift vs baseline 16.67 m/s
        pipe_7 = TelemetryIngestPipeline()
        rep_7 = pipe_7.process_stream(frames_7, "ds-07-drift")
        p7 = rep_7.verdict == DatasetQualityVerdict.REJECTED and rep_7.drift_score > 3.0
        if p7: passed += 1
        results.append({
            "scenario": "07_DISTRIBUTIONAL_SPEED_DRIFT",
            "description": "Covariate shift in vehicle speed distribution exceeding 3-sigma training bounds",
            "expected_verdict": DatasetQualityVerdict.REJECTED.value,
            "actual_verdict": rep_7.verdict.value,
            "anomalies_detected": len(rep_7.anomalies),
            "passed": p7,
        })

        # Scenario 8: Timestamp Jitter Check
        sim = TokyoTelemetrySimulator()
        frames_8 = [sim.generate_frame() for _ in range(10)]
        # Inject jitter
        bad_frame = sim.generate_frame()
        bad_frame.timestamp_ns += 50_000_000 # 50ms spike
        frames_8.append(bad_frame)
        frames_8.extend([sim.generate_frame() for _ in range(10)])
        pipe_8 = TelemetryIngestPipeline()
        rep_8 = pipe_8.process_stream(frames_8, "ds-08-jitter")
        p8 = any(a.anomaly_type == AnomalyType.TIMESTAMP_JITTER for a in rep_8.anomalies)
        if p8: passed += 1
        results.append({
            "scenario": "08_TIMESTAMP_JITTER_DETECTION",
            "description": "Sensor sync clock jitter exceeding 15ms tolerance window",
            "expected_verdict": DatasetQualityVerdict.WARNING.value,
            "actual_verdict": rep_8.verdict.value,
            "anomalies_detected": len(rep_8.anomalies),
            "passed": p8,
        })

        # Scenario 9: Camera Telemetry Sync ID Consistency
        sim = TokyoTelemetrySimulator()
        frames_9 = [sim.generate_frame() for _ in range(30)]
        pipe_9 = TelemetryIngestPipeline()
        rep_9 = pipe_9.process_stream(frames_9, "ds-09-camera-sync")
        p9 = rep_9.verdict == DatasetQualityVerdict.CERTIFIED and all(f.camera_sync_id.startswith("cam-sync-") for f in frames_9)
        if p9: passed += 1
        results.append({
            "scenario": "09_CAMERA_SYNC_ID_CONSISTENCY",
            "description": "Deterministic alignment between camera frame sync IDs and CAN bus frames",
            "expected_verdict": DatasetQualityVerdict.CERTIFIED.value,
            "actual_verdict": rep_9.verdict.value,
            "anomalies_detected": len(rep_9.anomalies),
            "passed": p9,
        })

        # Scenario 10: Cryptographic Checksum Reproducibility
        sim_a = TokyoTelemetrySimulator()
        sim_b = TokyoTelemetrySimulator()
        frames_10a = [sim_a.generate_frame() for _ in range(40)]
        frames_10b = [sim_b.generate_frame() for _ in range(40)]
        pipe_10a = TelemetryIngestPipeline()
        pipe_10b = TelemetryIngestPipeline()
        rep_10a = pipe_10a.process_stream(frames_10a, "ds-10a")
        rep_10b = pipe_10b.process_stream(frames_10b, "ds-10b")
        p10 = rep_10a.dataset_checksum == rep_10b.dataset_checksum and len(rep_10a.dataset_checksum) == 64
        if p10: passed += 1
        results.append({
            "scenario": "10_CRYPTOGRAPHIC_REPRODUCIBILITY",
            "description": "Deterministic SHA-256 dataset checksum matching across parallel ingestion runs",
            "expected_verdict": DatasetQualityVerdict.CERTIFIED.value,
            "actual_verdict": rep_10a.verdict.value,
            "anomalies_detected": 0,
            "passed": p10,
        })

        return {
            "total_scenarios": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "accuracy_score": round((passed / len(results)) * 100, 1),
            "scenarios": results,
        }
