"""Command-line interface."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from .services import get_services, load_config
from .processing import build_index_from_dir

console = Console()


@click.group()
def main():
    """Offline Document MCP – acquire, process, index, serve."""
    pass


@main.command()
@click.option("--service", default=None, help="Run only this service name")
@click.option("--force", is_flag=True)
@click.option("--root", type=click.Path(), default=".")
def acquire(service: str | None, force: bool, root: str):
    """Download / prepare documents from configured legal sources."""
    root_path = Path(root)
    services = get_services(root=root_path)
    if service:
        services = [s for s in services if s.name == service]
        if not services:
            console.print(f"[red]No service named '{service}'[/red]")
            return
    total = 0
    for svc in services:
        console.print(f"[bold]Running {svc.name}[/bold]")
        n = svc.acquire(force=force)
        total += n
    console.print(f"Done. Items touched: {total}")


@main.command()
@click.option("--root", type=click.Path(), default=".")
def process(root: str):
    """Placeholder for deeper cleaning / language filtering."""
    console.print("[yellow]Process step is a no-op in v0.1 – raw text is used directly.[/yellow]")
    console.print("Place cleaned .txt / .md files under data/ before indexing.")


@main.command()
@click.option("--root", type=click.Path(), default=".")
@click.option("--db", default="data/index.db")
def index(root: str, db: str):
    """Build local FTS index from data/ tree."""
    root_path = Path(root)
    db_path = root_path / db
    console.print(f"Indexing under {root_path / 'data'} → {db_path}")
    idx = build_index_from_dir(root_path / "data", db_path)
    stats = idx.stats()
    console.print(f"[green]Indexed {stats['documents']} docs / {stats['chunks']} chunks[/green]")


@main.command()
@click.option("--db", default="data/index.db")
@click.argument("query")
def search(db: str, query: str):
    """Quick CLI search against the local index."""
    from .processing.indexer import LocalIndex
    idx = LocalIndex(db)
    results = idx.search(query)
    for i, r in enumerate(results, 1):
        console.print(f"\n[bold]{i}. {r['title']}[/bold] ({r['path']})")
        console.print(r["content"][:400] + "...")


if __name__ == "__main__":
    main()
