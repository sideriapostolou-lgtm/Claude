"""Data export utilities for reports and analysis."""

import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Any
from rich.console import Console

console = Console()


def export_to_json(data: Any, filename: str, output_dir: str = "./output") -> Path:
    """Export data to JSON file."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    file_path = output_path / f"{filename}.json"

    with open(file_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    console.print(f"[green]✓ Exported to {file_path}[/green]")
    return file_path


def export_to_csv(data: list[dict], filename: str, output_dir: str = "./output") -> Path:
    """Export list of dictionaries to CSV file."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    file_path = output_path / f"{filename}.csv"

    if not data:
        console.print("[yellow]No data to export[/yellow]")
        return file_path

    # Get all unique keys from all dictionaries
    fieldnames = []
    for item in data:
        for key in item.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with open(file_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

    console.print(f"[green]✓ Exported to {file_path}[/green]")
    return file_path


def export_product_report(
    products: list[dict],
    analysis_results: list[dict],
    filename: str = None
) -> Path:
    """Export comprehensive product analysis report."""
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"product_report_{timestamp}"

    report = {
        "generated_at": datetime.now().isoformat(),
        "total_products": len(products),
        "products": products,
        "analysis": analysis_results,
        "summary": {
            "winners": len([a for a in analysis_results if a.get("score", 0) >= 80]),
            "high_potential": len([a for a in analysis_results if 65 <= a.get("score", 0) < 80]),
            "average_score": sum(a.get("score", 0) for a in analysis_results) / len(analysis_results) if analysis_results else 0,
        }
    }

    return export_to_json(report, filename)


def export_script_collection(
    scripts: list[dict],
    filename: str = None
) -> Path:
    """Export a collection of UGC scripts."""
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"ugc_scripts_{timestamp}"

    collection = {
        "generated_at": datetime.now().isoformat(),
        "total_scripts": len(scripts),
        "scripts": scripts,
    }

    return export_to_json(collection, filename)


def export_trend_report(
    trends: dict,
    filename: str = None
) -> Path:
    """Export trend analysis report."""
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"trend_report_{timestamp}"

    report = {
        "generated_at": datetime.now().isoformat(),
        **trends,
    }

    return export_to_json(report, filename)
