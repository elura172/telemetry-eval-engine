from pathlib import Path

from src.evals.ngsim_real_data import DEFAULT_DATA, evaluate, load_samples, run_gate


def test_bundled_ngsim_sample_is_one_contiguous_10hz_trajectory():
    samples = load_samples(DEFAULT_DATA)
    assert len(samples) == 600
    assert all(b.frame_id == a.frame_id + 1 for a, b in zip(samples, samples[1:]))
    assert all(b.timestamp_ns - a.timestamp_ns == 100_000_000 for a, b in zip(samples, samples[1:]))
    assert run_gate(samples) == set()


def test_ngsim_eval_reports_injection_confusion_and_measured_throughput():
    report = evaluate(DEFAULT_DATA, repeats=2)
    assert report["dataset"]["source_fault_labels_available"] is False
    assert report["dataset"]["sample_sha256"] == "2d7a829a64ec2e607e5c44095b67464b7aa19776c57f842a7ce1cfd692067bba"
    assert report["injected_faults"]["true_positive_rows"] == 1
    assert report["injected_faults"]["false_positive_rows_on_unmodified_data"] == 0
    assert report["injected_faults"]["false_negative_rows"] == 1
    assert report["injected_faults"]["precision"] == 1.0
    assert report["injected_faults"]["recall"] == 0.5
    assert report["throughput"]["records_evaluated"] == 1200
    assert report["throughput"]["records_per_second"] > 0


def test_longitudinal_acceleration_gate_is_applied():
    samples = load_samples(Path(DEFAULT_DATA))
    sample = samples[0]
    detected = run_gate(samples[:1], {sample.frame_id: 13.0})
    assert detected == {sample.frame_id}
