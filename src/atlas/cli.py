import click

from atlas.acquisition.connectors.bse import BSEConnector
from atlas.acquisition.policy import DEFAULT_POLICY
from atlas.acquisition.scaffold import RepositoryAlreadyExistsError, build_repository
from atlas.acquisition.workflow import run_acquisition
from atlas.app import Atlas


@click.group()
def cli() -> None:
    """Atlas — investment research platform."""


@cli.group()
def repository() -> None:
    """Manage company repositories."""


@repository.command()
@click.argument("ticker")
def build(ticker: str) -> None:
    """Create the repository structure for TICKER."""
    ticker = ticker.upper()
    atlas = Atlas.from_environment()
    try:
        path = build_repository(atlas, ticker)
        click.echo(f"Repository '{ticker}' created at {path}")
    except RepositoryAlreadyExistsError as e:
        click.echo(f"Repository '{ticker}' already exists at {e.path}. Nothing to do.")


@cli.command()
@click.argument("ticker")
def acquire(ticker: str) -> None:
    """Acquire all available evidence for TICKER."""
    ticker = ticker.upper()
    atlas = Atlas.from_environment()
    repo_root = atlas.settings.repository_base_path / ticker
    if not (repo_root / "company.json").exists():
        click.echo(
            f"No repository for '{ticker}'. Run: atlas repository build {ticker}",
            err=True,
        )
        raise SystemExit(1)

    click.echo(f"Atlas — Acquiring {ticker}\n")

    with BSEConnector.from_settings(atlas.settings) as connector:
        record = run_acquisition(repo_root, connector, DEFAULT_POLICY, on_progress=click.echo)

    click.echo("\nSummary")
    click.echo(f"  Discovered:      {record.discovered}")
    if record.selected != record.discovered:
        click.echo(f"  Selected:        {record.selected}  (policy: {record.policy_name})")
    click.echo(f"  Already present: {record.already_acquired}")
    click.echo(f"  New:             {record.new}")
    click.echo(f"  Downloaded:      {record.downloaded}")
    click.echo(f"  Failed:          {record.failed}")
    click.echo(f"  Duration:        {record.duration_seconds:.1f}s")
    if record.record_path:
        click.echo(f"  Record:          {record.record_path.name}")

    if record.warnings:
        click.echo("\nWarnings:")
        for w in record.warnings:
            if w.code == "UNMAPPED_SUBCATEGORY":
                count = w.metadata.get("count", "?")
                subcat = w.metadata.get("subcategory", "unknown")
                click.echo(
                    f"  {w.source.value}: {count} occurrence(s) of "
                    f"unmapped subcategory {subcat!r} — filed as OTHER"
                )
            else:
                click.echo(f"  [{w.source.value}] {w.message}: {w.metadata}")

    if record.failures:
        click.echo("\nFailed:")
        for f in record.failures:
            click.echo(f"  {f.title}: {f.error}")
