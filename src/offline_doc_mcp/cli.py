"""Command-line interface."""
from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from .processing import build_index_from_dir
from .services import get_services

console = Console()


@click.group()
def main():
    """Offline Document MCP – acquire, process, index, search and serve."""


@main.command()
@click.option("--service", default=None, help="Run only this service name")
@click.option("--force", is_flag=True, help="Replace already downloaded documents")
@click.option("--root", type=click.Path(), default=".")
@click.option("--query", default=None, help="Override a source's configured search query")
def acquire(service: str | None, force: bool, root: str, query: str | None):
    """Search configured legal sources and download permitted documents."""
    root_path = Path(root)
    services = get_services(root=root_path)
    if service:
        services = [item for item in services if item.name == service]
        if not services:
            console.print(f"[red]No service named '{service}'[/red]")
            return
    total = 0
    try:
        for svc in services:
            if query:
                svc.config["query"] = query
                if svc.name == "wikipedia_dumps":
                    svc.config["queries"] = [query]
            console.print(f"[bold]Running {svc.name}[/bold]")
            try:
                acquired = svc.acquire(force=force)
                total += acquired
                console.print(f"[green]{svc.name}: downloaded {acquired} document(s)[/green]")
            except Exception as exc:
                console.print(f"[red]{svc.name}: failed ({type(exc).__name__})[/red]")
    finally:
        for svc in services:
            svc.close()
    console.print(f"Done. Documents downloaded: {total}")


@main.command()
@click.option("--root", type=click.Path(), default=".")
def process(root: str):
    """Explain the supported input formats; raw text is indexed directly."""
    data_dir = Path(root) / "data"
    console.print(f"Place source-attributed .txt, .md, or .text files under {data_dir}.")
    console.print("The index command reads these files directly; no hidden network processing occurs.")


@main.command()
@click.option("--root", type=click.Path(), default=".")
@click.option("--db", default="data/index.db")
def index(root: str, db: str):
    """Build or refresh the local FTS index from downloaded text files."""
    root_path = Path(root)
    db_path = root_path / db
    console.print(f"Indexing under {root_path / 'data'} → {db_path}")
    index_obj = build_index_from_dir(root_path / "data", db_path)
    stats = index_obj.stats()
    console.print(f"[green]Indexed {stats['documents']} docs / {stats['chunks']} chunks[/green]")


@main.command()
@click.option("--db", default="data/index.db")
@click.option("--limit", default=8, type=click.IntRange(1, 50))
@click.argument("query")
def search(db: str, limit: int, query: str):
    """Search the local index and display source-bearing passages."""
    from .processing.indexer import LocalIndex
    results = LocalIndex(db).search(query, limit=limit)
    if not results:
        console.print("[yellow]No matches. Acquire and index documents first.[/yellow]")
    for i, result in enumerate(results, 1):
        console.print(f"\n[bold]{i}. {result['title']}[/bold] ({result['path']})")
        console.print(result["content"][:400] + "...")


if __name__ == "__main__":
    main()
