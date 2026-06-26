import click

from atlas.acquisition.acquisitions import save_acquisition_run
from atlas.acquisition.connectors.bse import BSEConnector
from atlas.acquisition.profile import DEFAULT_PROFILE
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
        report = run_acquisition(repo_root, connector, DEFAULT_PROFILE, on_progress=click.echo)

    run = save_acquisition_run(report, repo_root)

    click.echo("\nSummary")
    click.echo(f"  Discovered:      {report.discovered}")
    if report.selected != report.discovered:
        click.echo(f"  Selected:        {report.selected}  (profile: {report.profile})")
    click.echo(f"  Already present: {report.already_acquired}")
    click.echo(f"  New:             {report.new}")
    click.echo(f"  Downloaded:      {report.downloaded}")
    click.echo(f"  Failed:          {report.failed}")
    click.echo(f"  Duration:        {report.duration_seconds:.1f}s")
    click.echo(f"  Record:          {run.record_path.name}")

    if report.warnings:
        click.echo("\nWarnings:")
        for w in report.warnings:
            if w.code == "UNMAPPED_SUBCATEGORY":
                count = w.metadata.get("count", "?")
                subcat = w.metadata.get("subcategory", "unknown")
                click.echo(
                    f"  {w.source.value}: {count} occurrence(s) of "
                    f"unmapped subcategory {subcat!r} — filed as OTHER"
                )
            else:
                click.echo(f"  [{w.source.value}] {w.message}: {w.metadata}")

    if report.failed:
        click.echo("\nFailed:")
        for r in report.results:
            if not r.succeeded:
                click.echo(f"  {r.evidence.title}: {r.error}")
