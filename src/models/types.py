"""
Domain models and schema definitions for autonomous vehicle telemetry and dataset evaluation.
"""
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class DatasetQualityVerdict(str, Enum):
    CERTIFIED = "CERTIFIED"              # No configured quality gate reported an issue
    WARNING = "WARNING"                  # Minor anomalies detected; flagged for review
    REJECTED = "REJECTED"                # Significant corruption or drift; blocked from training


class AnomalyType(str, Enum):
    TIMESTAMP_JITTER = "TIMESTAMP_JITTER"            # Out-of-order or skipped timestamps
    KINEMATIC_VIOLATION = "KINEMATIC_VIOLATION"      # Impossible acceleration / velocity delta
    GPS_MULTIPATH_JUMP = "GPS_MULTIPATH_JUMP"        # Sensor teleportation / multipath anomaly
    IMU_SATURATION = "IMU_SATURATION"                # Sensor rail saturation / clipping
    DISTRIBUTION_DRIFT = "DISTRIBUTION_DRIFT"        # Covariate shift vs. reference baseline
    DROPPED_FRAME = "DROPPED_FRAME"                  # Missing sensor telemetry sequence


class VehicleTelemetryFrame(BaseModel):
    frame_id: int = Field(ge=0)
    vehicle_id: str = Field(min_length=1)
    timestamp_ns: int = Field(ge=0)
    speed_mps: float = Field(ge=0.0, le=100.0, allow_inf_nan=False)
    steering_angle_rad: float = Field(ge=-1.57, le=1.57, allow_inf_nan=False)
    accel_x: float = Field(allow_inf_nan=False)  # Longitudinal acceleration (m/s^2)
    accel_y: float = Field(allow_inf_nan=False)  # Lateral acceleration (m/s^2)
    accel_z: float = Field(allow_inf_nan=False)  # Vertical acceleration (m/s^2)
    gps_lat: float = Field(ge=-90.0, le=90.0, allow_inf_nan=False)
    gps_lon: float = Field(ge=-180.0, le=180.0, allow_inf_nan=False)
    imu_yaw_rate: float = Field(allow_inf_nan=False)
    camera_sync_id: str
    metadata: Dict[str, str] = Field(default_factory=dict)


class AnomalyEvent(BaseModel):
    frame_id: int
    timestamp_ns: int
    anomaly_type: AnomalyType
    severity: str  # LOW, MEDIUM, CRITICAL
    description: str
    metric_value: float
    threshold_value: float


class IngestReport(BaseModel):
    dataset_id: str
    total_frames_received: int
    clean_frames_sunk: int
    dropped_frames_count: int
    anomalies: List[AnomalyEvent]
    drift_score: float
    verdict: DatasetQualityVerdict
    dataset_checksum: str
    processing_time_ms: float
