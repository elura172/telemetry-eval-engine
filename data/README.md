# NGSIM evaluation sample

This repository includes a 600-row, single-trajectory excerpt from the Federal Highway Administration's Next Generation Simulation (NGSIM) vehicle trajectories dataset.

- Attribution: Federal Highway Administration, *Next Generation Simulation (NGSIM) Vehicle Trajectories and Supporting Data*, distributed by the U.S. DOT ITS DataHub.
- Dataset page: <https://data.transportation.gov/d/8ect-6jqj>
- Record API: <https://data.transportation.gov/resource/8ect-6jqj.csv>
- License shown in the Data.gov catalog: [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/)
- API filter: `vehicle_id=396 AND total_frames=1628`, ordered by `global_time`, first 600 rows; selected columns are retained in the CSV.
- Retrieved: 2026-10-24.
- Sample SHA-256: `2d7a829a64ec2e607e5c44095b67464b7aa19776c57f842a7ce1cfd692067bba`.

The source describes video-derived vehicle trajectories recorded every 0.1 seconds. Its `v_acc` field is in feet/second squared. The evaluation converts that field to meters/second squared before applying the engine's acceleration gate. This is road-trajectory evidence, not GPS/IMU telemetry; the source has no sensor-fault labels. Reported false positives and misses therefore apply only to the explicitly injected value edits under the stated assumption that all unmodified rows are clean.
