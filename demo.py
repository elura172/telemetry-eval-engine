#!/usr/bin/env python3
"""Independent portfolio demo of simulated telemetry checks and evaluation scenarios."""
import time
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from src.models.types import DatasetQualityVerdict
from src.telemetry.stream import TokyoTelemetrySimulator
from src.telemetry.sink import TelemetryIngestPipeline
from src.evals.harness import TelemetryBenchmarkSuite

console = Console()


def print_banner():
    banner_text = (
        "[bold cyan]TELEMETRY EVAL ENGINE // INDEPENDENT PROTOTYPE[/bold cyan]\n"
        "[dim]Simulated Telemetry, Anomaly Detection & Dataset Integrity Checks[/dim]\n"
        "[dim]Portfolio project; not affiliated with Woven by Toyota[/dim]\n"
        "[dim white]Author: Paul Trafford (elura172) · Tokyo Relocation Pipeline Candidate[/dim white]"
    )
    console.print(Panel(banner_text, border_style="cyan", box=box.DOUBLE))


def run_simulated_telemetry():
    console.print("\n[bold yellow]▶ STEP 1: Simulated 50Hz Vehicle Telemetry Stream (Tokyo Loop)[/bold yellow]")
    sim = TokyoTelemetrySimulator()
    pipeline = TelemetryIngestPipeline()

    console.print("  [dim]Simulating vehicle: woven-av-tokyo-01 (Shuto Expressway Route C1 / Nihonbashi)...[/dim]")
    
    # Generate batch with 1 clean run, then inject GPS jump and IMU spike
    frames = [sim.generate_frame() for _ in range(40)]
    frames.append(sim.generate_frame(inject_gps_jump=True))
    frames.extend([sim.generate_frame() for _ in range(10)])
    frames.append(sim.generate_frame(inject_imu_saturation=True))
    frames.extend([sim.generate_frame() for _ in range(10)])

    report = pipeline.process_stream(frames, dataset_id="tokyo-expressway-run-882")

    console.print(f"  Total Frames Received: [bold]{report.total_frames_received}[/bold]")
    console.print(f"  Clean Frames Sunk: [bold green]{report.clean_frames_sunk}[/bold green]")
    console.print(f"  Dropped Frames: [bold]{report.dropped_frames_count}[/bold]")
    console.print(f"  Anomalies Intercepted: [bold red]{len(report.anomalies)}[/bold red]")

    for idx, anomaly in enumerate(report.anomalies, 1):
        console.print(f"    [red]• [{anomaly.anomaly_type.value}][/red] {anomaly.description} (Severity: [bold yellow]{anomaly.severity}[/bold yellow])")

    verdict_style = "green" if report.verdict == DatasetQualityVerdict.CERTIFIED else ("yellow" if report.verdict == DatasetQualityVerdict.WARNING else "red")
    console.print(f"  Dataset Quality Verdict: [{verdict_style}][bold]{report.verdict.value}[/bold][/{verdict_style}]")
    console.print(f"  SHA-256 Dataset Checksum: [dim]{report.dataset_checksum}[/dim]")
    console.print(f"  Ingest Processing Latency: [cyan]{report.processing_time_ms} ms[/cyan]")


def run_benchmark():
    console.print("\n[bold yellow]▶ STEP 2: Running 10-Scenario Automated Evaluation Suite[/bold yellow]\n")
    suite = TelemetryBenchmarkSuite()
    benchmark_res = suite.run_benchmark()

    table = Table(title="Synthetic Telemetry Scenario Benchmark", box=box.ROUNDED, padding=(0, 1))
    table.add_column("Scenario", style="bold cyan", max_width=16, no_wrap=True, overflow="ellipsis")
    table.add_column("Case", style="white", max_width=23, no_wrap=True, overflow="ellipsis")
    table.add_column("Expected", style="magenta", width=9, no_wrap=True)
    table.add_column("Actual", style="bold", width=9, no_wrap=True)
    table.add_column("Result", style="bold", width=6, no_wrap=True)

    for sc in benchmark_res["scenarios"]:
        status_str = "[bold green]PASS[/bold green]" if sc["passed"] else "[bold red]FAIL[/bold red]"
        verdict_style = "green" if sc["actual_verdict"] == "CERTIFIED" else ("yellow" if sc["actual_verdict"] == "WARNING" else "red")
        table.add_row(
            sc["scenario"],
            sc["description"],
            sc["expected_verdict"],
            f"[{verdict_style}]{sc['actual_verdict']}[/{verdict_style}]",
            status_str,
        )

    console.print(table)

    summary_panel = Panel(
        f"[bold]Total Scenarios:[/bold] {benchmark_res['total_scenarios']} | "
        f"[bold green]Passed:[/bold green] {benchmark_res['passed']} | "
        f"[bold red]Failed:[/bold red] {benchmark_res['failed']} | "
        f"[bold cyan]Scenario Pass Rate:[/bold cyan] [bold green]{benchmark_res['pass_rate_pct']}%[/bold green]",
        border_style="green",
        title="Fixed Simulator Scenarios",
    )
    console.print(summary_panel)


def main():
    print_banner()
    run_simulated_telemetry()
    time.sleep(0.5)
    run_benchmark()


if __name__ == "__main__":
    main()
