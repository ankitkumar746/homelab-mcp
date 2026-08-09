#!/usr/bin/env python3
"""Homelab MCP Log Viewer — rich CLI analytics for JSONL log files."""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def find_log_files(log_dir: Path, date_filter: str | None = None) -> list[Path]:
    """Find log files, optionally filtered by date prefix."""
    if not log_dir.exists():
        return []
    files = sorted(log_dir.glob("homelab_mcp_*.jsonl"))
    if date_filter:
        date_str = date_filter.replace("-", "")
        files = [f for f in files if date_str in f.name]
    return files


def parse_entries(file_path: Path) -> list[dict]:
    """Parse a JSONL file into a list of dicts."""
    entries = []
    try:
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return entries


def load_all_entries(files: list[Path]) -> list[dict]:
    """Load and merge entries from multiple files."""
    all_entries = []
    for f in files:
        all_entries.extend(parse_entries(f))
    return all_entries


def filter_entries(entries: list[dict], args) -> list[dict]:
    """Apply filters from CLI args."""
    filtered = entries
    if args.tool:
        filtered = [e for e in filtered if e.get("tool") == args.tool]
    if args.errors:
        filtered = [
            e for e in filtered if e.get("status") in ("error",) or e.get("level") == "ERROR"
        ]
    if args.safety:
        filtered = [e for e in filtered if e.get("event", "").startswith("safety.")]
    return filtered


def percentile(sorted_values: list[float], p: float) -> float:
    """Compute percentile from a sorted list."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def display_overview(entries: list[dict], source_desc: str):
    """Display the overview panel + stats tables."""
    tool_calls = [e for e in entries if e.get("event") == "tool.call"]
    tool_responses = [e for e in entries if e.get("event") == "tool.response"]
    tool_errors = [e for e in entries if e.get("event") == "tool.error"]
    blocked = [e for e in entries if e.get("event") == "safety.blocked"]
    confirmed = [e for e in entries if e.get("event") == "safety.confirm"]
    rejected = [e for e in entries if e.get("event") == "safety.rejected"]
    durations = [e["duration_ms"] for e in tool_responses if e.get("duration_ms") is not None]

    # Time range
    timestamps = [e.get("ts", "") for e in entries if e.get("ts")]
    period = "N/A"
    if timestamps:
        first = timestamps[0][:19]
        last = timestamps[-1][:19]
        period = f"{first} → {last}"

    console.print(
        Panel(
            f"[bold]Source:[/bold] {source_desc}\n"
            f"[bold]Period:[/bold] {period}\n"
            f"[bold]Entries:[/bold] {len(entries)}",
            title="[bold cyan]Homelab MCP — Log Summary[/bold cyan]",
            border_style="cyan",
        )
    )

    # Overview table
    overview = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    overview.add_column("Metric", style="dim")
    overview.add_column("Value", justify="right", style="bold")
    overview.add_row("Total tool calls", str(len(tool_calls)))
    overview.add_row("Successful", f"[green]{len(tool_responses)}[/green]")
    overview.add_row("Errors", f"[red]{len(tool_errors)}[/red]" if tool_errors else "0")

    if durations:
        sorted_d = sorted(durations)
        avg = sum(sorted_d) / len(sorted_d)
        overview.add_row("Avg response time", f"{avg:.1f}ms")
        overview.add_row("P50 response time", f"{percentile(sorted_d, 50):.1f}ms")
        overview.add_row("P95 response time", f"{percentile(sorted_d, 95):.1f}ms")
        overview.add_row("Max response time", f"{max(sorted_d):.1f}ms")
    else:
        overview.add_row("Avg response time", "N/A")

    console.print()
    console.print(overview)

    # Safety section
    safety_count = len(blocked) + len(confirmed) + len(rejected)
    if safety_count > 0:
        console.print()
        safety_table = Table(
            title="[bold yellow]Safety Events[/bold yellow]",
            show_header=True,
            header_style="bold",
        )
        safety_table.add_column("Command", style="cyan", max_width=50, no_wrap=False)
        safety_table.add_column("Level", justify="center")
        safety_table.add_column("Status", justify="center")
        safety_table.add_column("Reason", max_width=40)

        for e in blocked:
            safety_table.add_row(
                e.get("command", ""),
                "[bold red]BLOCKED[/bold red]",
                "—",
                e.get("detail", ""),
            )
        for e in confirmed:
            req_id = e.get("request_id")
            matching_reject = any(
                r.get("request_id") == req_id and r.get("event") == "safety.rejected"
                for r in rejected
            )
            status = "[red]Rejected[/red]" if matching_reject else "[green]Approved[/green]"
            safety_table.add_row(
                e.get("command", ""),
                "[yellow]CONFIRM[/yellow]",
                status,
                e.get("detail", ""),
            )
        for e in rejected:
            req_id = e.get("request_id")
            if not any(
                c.get("request_id") == req_id and c.get("event") == "safety.confirm"
                for c in confirmed
            ):
                safety_table.add_row(
                    e.get("command", ""),
                    "[yellow]CONFIRM[/yellow]",
                    "[red]Rejected[/red]",
                    e.get("detail", ""),
                )

        console.print(safety_table)

    # Top 10 most called tools
    if tool_calls:
        tool_counter = Counter(e.get("tool", "unknown") for e in tool_calls)
        console.print()
        top_table = Table(
            title="[bold green]Top 10 Most Called Tools[/bold green]",
            show_header=True,
            header_style="bold",
        )
        top_table.add_column("#", justify="right", style="dim", width=3)
        top_table.add_column("Tool", style="cyan")
        top_table.add_column("Calls", justify="right")
        top_table.add_column("Avg (ms)", justify="right")

        # Compute avg duration per tool
        tool_durations: dict[str, list[float]] = {}
        for e in tool_responses:
            t = e.get("tool")
            d = e.get("duration_ms")
            if t and d is not None:
                tool_durations.setdefault(t, []).append(d)

        for i, (tool, count) in enumerate(tool_counter.most_common(10), 1):
            ds = tool_durations.get(tool, [])
            avg_d = f"{sum(ds) / len(ds):.1f}" if ds else "—"
            top_table.add_row(str(i), tool, str(count), avg_d)

        console.print(top_table)

    # Top 10 slowest requests
    if tool_responses:
        sorted_by_duration = sorted(
            [e for e in tool_responses if e.get("duration_ms") is not None],
            key=lambda e: e["duration_ms"],
            reverse=True,
        )[:10]

        if sorted_by_duration:
            console.print()
            slow_table = Table(
                title="[bold red]Top 10 Slowest Requests[/bold red]",
                show_header=True,
                header_style="bold",
            )
            slow_table.add_column("#", justify="right", style="dim", width=3)
            slow_table.add_column("Duration", justify="right", style="bold red")
            slow_table.add_column("Tool", style="cyan")
            slow_table.add_column("Node")
            slow_table.add_column("Request ID", style="dim")

            for i, e in enumerate(sorted_by_duration, 1):
                slow_table.add_row(
                    str(i),
                    f"{e['duration_ms']:.1f}ms",
                    e.get("tool", ""),
                    e.get("node", "") or "—",
                    e.get("request_id", "") or "—",
                )

            console.print(slow_table)

    # Recent errors
    if tool_errors:
        console.print()
        err_table = Table(
            title="[bold red]Recent Errors[/bold red]",
            show_header=True,
            header_style="bold",
        )
        err_table.add_column("Time", style="dim")
        err_table.add_column("Tool", style="cyan")
        err_table.add_column("Error", max_width=60)

        for e in tool_errors[-10:]:
            err_table.add_row(
                e.get("ts", "")[:19],
                e.get("tool", ""),
                e.get("detail", "")[:80],
            )

        console.print(err_table)


def display_tail(log_dir: Path):
    """Live tail the latest log file."""
    files = find_log_files(log_dir)
    if not files:
        console.print("[red]No log files found[/red]")
        return

    latest = files[-1]
    console.print(f"[dim]Tailing {latest.name} (Ctrl+C to stop)...[/dim]\n")

    with open(latest, encoding="utf-8") as f:
        f.seek(0, 2)  # Seek to end
        try:
            while True:
                line = f.readline()
                if line:
                    try:
                        entry = json.loads(line.strip())
                        level = entry.get("level", "")
                        event = entry.get("event", "")
                        tool = entry.get("tool", "")
                        detail = entry.get("detail", "")
                        duration = entry.get("duration_ms")
                        status = entry.get("status", "")

                        ts_short = entry.get("ts", "")[11:19]

                        if level == "ERROR":
                            color = "red"
                        elif level == "WARNING":
                            color = "yellow"
                        elif event == "tool.call":
                            color = "cyan"
                        else:
                            color = "green"

                        dur_str = f" [dim]{duration}ms[/dim]" if duration else ""
                        stat_str = f" [{color}]{status}[/{color}]" if status else ""
                        console.print(
                            f"[dim]{ts_short}[/dim] [{color}]{level:5}[/{color}] "
                            f"[bold]{event:16}[/bold] {tool:20} {detail}{dur_str}{stat_str}"
                        )
                    except json.JSONDecodeError:
                        pass
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped.[/dim]")


def export_entries(entries: list[dict], fmt: str, output: str | None):
    """Export entries to CSV or JSON."""
    if fmt == "json":
        data = json.dumps(entries, indent=2, ensure_ascii=False)
        if output:
            Path(output).write_text(data, encoding="utf-8")
            console.print(f"[green]Exported {len(entries)} entries to {output}[/green]")
        else:
            console.print(data)
    elif fmt == "csv":
        import csv

        fields = [
            "ts",
            "level",
            "event",
            "tool",
            "node",
            "duration_ms",
            "status",
            "safety_level",
            "command",
            "detail",
            "request_id",
        ]
        writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for e in entries:
            writer.writerow(e)
        if output:
            console.print(f"\n[green]Redirect to file: {output}[/green]")


def main():
    parser = argparse.ArgumentParser(
        description="Homelab MCP log viewer — analytics for JSONL log files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  homelab-logview                    # Latest log file summary\n"
            "  homelab-logview --all              # All log files aggregated\n"
            "  homelab-logview --date 2026-08-01  # Specific date\n"
            "  homelab-logview --tail             # Live tail\n"
            "  homelab-logview --tool check_service  # Filter by tool\n"
            "  homelab-logview --safety           # Safety events only\n"
            "  homelab-logview --all --export csv > report.csv\n"
        ),
    )
    parser.add_argument("--file", type=str, help="Specific log file to analyze")
    parser.add_argument("--all", action="store_true", help="Aggregate all log files")
    parser.add_argument("--date", type=str, help="Filter by date (YYYY-MM-DD)")
    parser.add_argument("--tail", action="store_true", help="Live follow latest log file")
    parser.add_argument("--tool", type=str, help="Filter by tool name")
    parser.add_argument("--errors", action="store_true", help="Show only errors")
    parser.add_argument("--safety", action="store_true", help="Show only safety events")
    parser.add_argument("--export", choices=["csv", "json"], help="Export data")
    parser.add_argument("--log-dir", type=str, default="logs", help="Log directory (default: logs)")
    args = parser.parse_args()

    log_dir = Path(args.log_dir)

    # Handle --tail mode
    if args.tail:
        display_tail(log_dir)
        return

    # Determine which files to load
    if args.file:
        files = [Path(args.file)]
        if not files[0].exists():
            console.print(f"[red]File not found: {args.file}[/red]")
            sys.exit(1)
        source_desc = files[0].name
    elif args.all:
        files = find_log_files(log_dir)
        if not files:
            console.print(f"[red]No log files found in {log_dir}/[/red]")
            sys.exit(1)
        source_desc = f"{len(files)} files from {log_dir}/"
    elif args.date:
        files = find_log_files(log_dir, date_filter=args.date)
        if not files:
            console.print(f"[red]No log files found for date {args.date}[/red]")
            sys.exit(1)
        source_desc = f"{len(files)} files matching {args.date}"
    else:
        # Default: latest file
        files = find_log_files(log_dir)
        if not files:
            console.print(f"[red]No log files found in {log_dir}/[/red]")
            sys.exit(1)
        files = [files[-1]]
        source_desc = files[0].name

    # Load and filter entries
    entries = load_all_entries(files)
    if not entries:
        console.print("[yellow]No log entries found.[/yellow]")
        sys.exit(0)

    entries = filter_entries(entries, args)

    # Handle export mode
    if args.export:
        export_entries(entries, args.export, None)
        return

    # Display
    display_overview(entries, source_desc)


if __name__ == "__main__":
    main()
