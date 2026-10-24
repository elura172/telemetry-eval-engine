"""Physical plausibility and simple speed-mean drift checks."""
import math
from typing import List, Optional, Tuple
from src.models.types import AnomalyEvent, AnomalyType, VehicleTelemetryFrame


class AnomalyDetector:
    """
    Validates physical plausibility, sensor limits, and temporal consistency of telemetry streams.
    """
    def __init__(
        self,
        max_longitudinal_accel: float = 12.0,
        max_lateral_accel: float = 8.5,
        imu_saturation_limit: float = 30.0,
        max_gps_jump_meters_per_sec: float = 80.0,
        expected_period_ns: int = 20_000_000, # 20 ms
        max_jitter_ns: int = 15_000_000,
    ):
        self.max_longitudinal_accel = max_longitudinal_accel
        self.max_lateral_accel = max_lateral_accel
        self.imu_saturation_limit = imu_saturation_limit
        self.max_gps_jump_mps = max_gps_jump_meters_per_sec
        self.expected_period_ns = expected_period_ns
        self.max_jitter_ns = max_jitter_ns

        self._last_frame: Optional[VehicleTelemetryFrame] = None

    def reset(self) -> None:
        """Clear temporal state before evaluating an independent dataset."""
        self._last_frame = None

    def inspect_frame(self, frame: VehicleTelemetryFrame) -> List[AnomalyEvent]:
        anomalies = self.inspect_accelerations(
            frame_id=frame.frame_id,
            timestamp_ns=frame.timestamp_ns,
            accel_x=frame.accel_x,
            accel_y=frame.accel_y,
        )

        # 3. Temporal Jitter and Sequence Checks against Prior Frame
        if self._last_frame is not None:
            dt_ns = frame.timestamp_ns - self._last_frame.timestamp_ns
            jitter = abs(dt_ns - self.expected_period_ns)
            if jitter > self.max_jitter_ns:
                anomalies.append(
                    AnomalyEvent(
                        frame_id=frame.frame_id,
                        timestamp_ns=frame.timestamp_ns,
                        anomaly_type=AnomalyType.TIMESTAMP_JITTER,
                        severity="MEDIUM",
                        description=f"Timestamp jitter {jitter / 1e6:.1f}ms exceeds tolerance",
                        metric_value=jitter / 1e6,
                        threshold_value=self.max_jitter_ns / 1e6,
                    )
                )

            # GPS Spatial Jump Check (approximate Haversine formula)
            dlat = (frame.gps_lat - self._last_frame.gps_lat) * 111_000
            dlon = (frame.gps_lon - self._last_frame.gps_lon) * 111_000 * math.cos(math.radians(frame.gps_lat))
            distance_meters = math.sqrt(dlat * dlat + dlon * dlon)
            # A non-positive delta is a clock/order fault; dividing by a tiny
            # clamped interval would manufacture a GPS teleportation alarm.
            speed_gps_mps = distance_meters / (dt_ns / 1e9) if dt_ns > 0 else 0.0

            if dt_ns > 0 and speed_gps_mps > self.max_gps_jump_mps:
                anomalies.append(
                    AnomalyEvent(
                        frame_id=frame.frame_id,
                        timestamp_ns=frame.timestamp_ns,
                        anomaly_type=AnomalyType.GPS_MULTIPATH_JUMP,
                        severity="CRITICAL",
                        description=f"GPS teleportation detected: apparent speed {speed_gps_mps:.1f} m/s",
                        metric_value=speed_gps_mps,
                        threshold_value=self.max_gps_jump_mps,
                    )
                )

        self._last_frame = frame
        return anomalies

    def inspect_accelerations(
        self,
        frame_id: int,
        timestamp_ns: int,
        accel_x: float,
        accel_y: float,
    ) -> List[AnomalyEvent]:
        """Evaluate acceleration fields without requiring unrelated GPS/camera data."""
        anomalies: List[AnomalyEvent] = []

        # 1. IMU Saturation Check
        if abs(accel_x) >= self.imu_saturation_limit or abs(accel_y) >= self.imu_saturation_limit:
            anomalies.append(
                AnomalyEvent(
                    frame_id=frame_id,
                    timestamp_ns=timestamp_ns,
                    anomaly_type=AnomalyType.IMU_SATURATION,
                    severity="CRITICAL",
                    description=f"IMU sensor rail saturated (accel_x={accel_x:.1f}, accel_y={accel_y:.1f})",
                    metric_value=max(abs(accel_x), abs(accel_y)),
                    threshold_value=self.imu_saturation_limit,
                )
            )

        # 2. Kinematic Plausibility Checks
        else:
            anomalies.extend(self.inspect_longitudinal_acceleration(frame_id, timestamp_ns, accel_x))
            if abs(accel_y) > self.max_lateral_accel:
                anomalies.append(
                    AnomalyEvent(
                        frame_id=frame_id,
                        timestamp_ns=timestamp_ns,
                        anomaly_type=AnomalyType.KINEMATIC_VIOLATION,
                        severity="HIGH",
                        description=f"Lateral acceleration {accel_y:.2f} m/s^2 violates road friction limit",
                        metric_value=abs(accel_y),
                        threshold_value=self.max_lateral_accel,
                    )
                )
        return anomalies

    def inspect_longitudinal_acceleration(
        self,
        frame_id: int,
        timestamp_ns: int,
        accel_x: float,
    ) -> List[AnomalyEvent]:
        """Check longitudinal acceleration without assuming an IMU source."""
        if abs(accel_x) <= self.max_longitudinal_accel:
            return []
        return [
            AnomalyEvent(
                frame_id=frame_id,
                timestamp_ns=timestamp_ns,
                anomaly_type=AnomalyType.KINEMATIC_VIOLATION,
                severity="HIGH",
                description=f"Longitudinal acceleration {accel_x:.2f} m/s^2 exceeds configured limit",
                metric_value=abs(accel_x),
                threshold_value=self.max_longitudinal_accel,
            )
        ]


class DistributionDriftDetector:
    """
    Computes statistical distribution shift between incoming telemetry batches and a canonical baseline dataset.
    """
    def __init__(self, baseline_mean_speed: float = 16.67, baseline_std_speed: float = 3.5):
        self.baseline_mean_speed = baseline_mean_speed
        self.baseline_std_speed = baseline_std_speed

    def compute_drift(self, frames: List[VehicleTelemetryFrame]) -> Tuple[float, Optional[AnomalyEvent]]:
        if not frames:
            return 0.0, None

        speeds = [f.speed_mps for f in frames]
        batch_mean = sum(speeds) / len(speeds)
        
        # Standardized z-score distance of mean
        drift_score = abs(batch_mean - self.baseline_mean_speed) / max(0.1, self.baseline_std_speed)

        anomaly = None
        if drift_score > 2.5: # 2.5 sigma shift
            anomaly = AnomalyEvent(
                frame_id=frames[-1].frame_id,
                timestamp_ns=frames[-1].timestamp_ns,
                anomaly_type=AnomalyType.DISTRIBUTION_DRIFT,
                severity="HIGH",
                description=f"Batch speed distribution shifted significantly from baseline (drift={drift_score:.2f})",
                metric_value=drift_score,
                threshold_value=2.5,
            )

        return drift_score, anomaly
