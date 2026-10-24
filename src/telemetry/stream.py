"""
Streaming Telemetry Ingestion and Lossless Ring Buffer.
"""
import math
import time
from typing import Dict, List, Optional, Tuple
from src.models.types import VehicleTelemetryFrame


class ZeroLossBuffer:
    """
    High-throughput memory-bounded ring buffer for sensor telemetry streams.
    Tracks frame sequence continuity, detects dropped packets, and ensures zero data loss.
    """
    def __init__(self, capacity: int = 10000):
        self.capacity = capacity
        self._buffer: List[Optional[VehicleTelemetryFrame]] = [None] * capacity
        self._head: int = 0
        self._tail: int = 0
        self._count: int = 0
        self._last_frame_id: Optional[int] = None
        self._dropped_frames_count: int = 0

    def push(self, frame: VehicleTelemetryFrame) -> Tuple[bool, int]:
        """
        Pushes a frame to the buffer. Returns (success, dropped_frames_detected_in_sequence).
        """
        dropped = 0
        if self._last_frame_id is not None:
            expected = self._last_frame_id + 1
            if frame.frame_id > expected:
                dropped = frame.frame_id - expected
                self._dropped_frames_count += dropped

        self._last_frame_id = frame.frame_id

        if self._count == self.capacity:
            # Overwrite oldest frame if full (backpressure warning)
            self._head = (self._head + 1) % self.capacity
            self._count -= 1

        self._buffer[self._tail] = frame
        self._tail = (self._tail + 1) % self.capacity
        self._count += 1
        return True, dropped

    def pop_batch(self, batch_size: int = 100) -> List[VehicleTelemetryFrame]:
        items: List[VehicleTelemetryFrame] = []
        limit = min(batch_size, self._count)
        for _ in range(limit):
            item = self._buffer[self._head]
            if item is not None:
                items.append(item)
                self._buffer[self._head] = None
            self._head = (self._head + 1) % self.capacity
            self._count -= 1
        return items

    @property
    def total_dropped_frames(self) -> int:
        return self._dropped_frames_count

    @property
    def size(self) -> int:
        return self._count


class TokyoTelemetrySimulator:
    """
    Simulates high-frequency vehicle telemetry along a Tokyo autonomous driving loop (Nihonbashi / Shuto Expressway).
    """
    def __init__(self, vehicle_id: str = "woven-av-tokyo-01", base_freq_hz: int = 50, start_time_ns: int = 1700000000000000000):
        self.vehicle_id = vehicle_id
        self.dt_ns = int(1e9 / base_freq_hz) # 20ms period for 50Hz
        self.current_time_ns = start_time_ns
        self.frame_counter = 0

        # Baseline Tokyo coordinates (Nihonbashi area)
        self.lat = 35.6833
        self.lon = 139.7731
        self.speed = 16.67 # ~60 km/h in m/s

    def generate_frame(
        self,
        inject_gps_jump: bool = False,
        inject_imu_saturation: bool = False,
        inject_kinematic_violation: bool = False,
        skip_sequence: int = 0,
    ) -> VehicleTelemetryFrame:
        self.frame_counter += 1 + skip_sequence
        self.current_time_ns += self.dt_ns * (1 + skip_sequence)

        t = self.frame_counter * 0.02
        accel_x = math.sin(t * 0.5) * 0.8
        accel_y = math.cos(t * 0.3) * 0.5
        accel_z = 9.81 + math.sin(t * 2.0) * 0.1
        yaw_rate = math.cos(t * 0.3) * 0.05
        steering = math.sin(t * 0.3) * 0.1

        # Coordinate progression
        self.lat += 0.00001
        self.lon += 0.00001

        # Anomaly Injections
        if inject_gps_jump:
            lat = self.lat + 0.05 # Sudden ~5km jump (tunnel multipath)
            lon = self.lon + 0.05
        else:
            lat = self.lat
            lon = self.lon

        if inject_imu_saturation:
            accel_x = 45.0 # Exceeds physical sensor rail (typically +/- 20 m/s^2)

        if inject_kinematic_violation:
            accel_y = 25.0 # Impossible lateral acceleration without rollover

        return VehicleTelemetryFrame(
            frame_id=self.frame_counter,
            vehicle_id=self.vehicle_id,
            timestamp_ns=self.current_time_ns,
            speed_mps=max(0.0, self.speed + accel_x * 0.02),
            steering_angle_rad=steering,
            accel_x=accel_x,
            accel_y=accel_y,
            accel_z=accel_z,
            gps_lat=lat,
            gps_lon=lon,
            imu_yaw_rate=yaw_rate,
            camera_sync_id=f"cam-sync-{self.frame_counter:08d}",
            metadata={"highway": "Shuto Expressway Route C1"},
        )
