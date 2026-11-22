"""Command-line interface."""
from __future__ import annotations

import signal
from pathlib import Path

import click
from rich.console import Console

from .acquire import DownloadState, PausedDownload, STOP_REQUESTED
from .processing import build_index_from_dir
from .services import get_services

console = Console()


@click.group()
def main():
    """Offline Document MCP – acquire, process, index, search and serve."""


@main.command()
@click.option("--service", default=None, help="Run only this service name")
@click.option("--force", is_flag=True, help="Retry failed or replace already downloaded documents")
@click.option("--root", type=click.Path(), default=".")
@click.option("--query", default=None, help="Override a source's configured search query")
@click.option("--max-bytes-per-run", type=click.IntRange(min=1), default=None,
              help="Pause acquisition after this many downloaded bytes")
@click.option("--quarantine-dir", default="data/quarantine",
              help="Directory for rejected files")
def acquire(service: str | None, force: bool, root: str, query: str | None,
            max_bytes_per_run: int | None, quarantine_dir: str):
    """Search configured legal sources and download permitted documents."""
    root_path = Path(root)
    services = get_services(root=root_path)
    if service:
        services = [item for item in services if item.name == service]
        if not services:
            console.print(f"[red]No service named '{service}'[/red]")
            return

    STOP_REQUESTED.clear()
    old_handlers = {}
    def request_stop(signum, frame):
        STOP_REQUESTED.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        old_handlers[signum] = signal.signal(signum, request_stop)

    total = 0
    remaining = max_bytes_per_run
    try:
        for svc in services:
            if STOP_REQUESTED.is_set():
                break
            if query:
                svc.config["query"] = query
                if svc.name == "wikipedia_dumps":
                    svc.config["queries"] = [query]
            svc.downloader.quarantine_dir = root_path / quarantine_dir
            svc.downloader.max_bytes_per_run = remaining
            console.print(f"[bold]Running {svc.name}[/bold]")
            try:
                acquired = svc.acquire(force=force)
                total += acquired
                console.print(f"[green]{svc.name}: downloaded {acquired} document(s)[/green]")
            except PausedDownload:
                console.print(f"[yellow]{svc.name}: paused; partial data is saved for resume[/yellow]")
                STOP_REQUESTED.set()
            except Exception as exc:
                console.print(f"[red]{svc.name}: failed ({type(exc).__name__})[/red]")
            finally:
                if remaining is not None:
                    remaining = max(0, remaining - svc.downloader.bytes_this_run)
                svc.close()
    finally:
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
        STOP_REQUESTED.clear()
    console.print(f"Done. Documents downloaded: {total}")
    if remaining == 0:
        console.print("[yellow]Run byte budget reached; pending downloads can resume on the next run.[/yellow]")


@main.command()
@click.option("--root", type=click.Path(), default=".")
@click.option("--db", default="data/download-state.sqlite3")
def status(root: str, db: str):
    """Show acquisition lifecycle state without exposing document contents."""
    state = DownloadState(Path(root) / db)
    with state.connect() as connection:
        rows = connection.execute(
            "SELECT state, COUNT(*) FROM downloads GROUP BY state ORDER BY state"
        ).fetchall()
    if not rows:
        console.print("[yellow]No acquisition records yet. Run acquire first.[/yellow]")
        return
    for name, count in rows:
        console.print(f"{name}: {count}")


@main.command()
@click.option("--root", type=click.Path(), default=".")
def process(root: str):
    """Explain supported input formats; raw text is indexed directly."""
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
