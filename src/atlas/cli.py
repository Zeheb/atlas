import click

from atlas.acquisition.acquisitions import save_acquisition_run
from atlas.acquisition.connectors.bse import BSEConnector
from atlas.acquisition.profile import COMPREHENSIVE_PROFILE, DEFAULT_PROFILE

_PROFILES = {
    DEFAULT_PROFILE.name: DEFAULT_PROFILE,
    COMPREHENSIVE_PROFILE.name: COMPREHENSIVE_PROFILE,
}
from atlas.acquisition.scaffold import RepositoryAlreadyExistsError, build_repository
from atlas.acquisition.workflow import run_acquisition
from atlas.app import Atlas
from atlas.query.engine import available_queries, run_query
from atlas.query.render import render_result


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
@click.option(
    "--profile",
    "profile_name",
    default="default",
    show_default=True,
    type=click.Choice(list(_PROFILES)),
    help="Acquisition profile to use.",
)
def acquire(ticker: str, profile_name: str) -> None:
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

    profile = _PROFILES[profile_name]
    click.echo(f"Atlas — Acquiring {ticker}\n")

    with BSEConnector.from_settings(atlas.settings) as connector:
        report = run_acquisition(repo_root, connector, profile, on_progress=click.echo)

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


# ---------------------------------------------------------------------------
# profile commands
# ---------------------------------------------------------------------------


@cli.group()
def profile() -> None:
    """Build and inspect company profiles."""


@profile.command("build")
@click.argument("ticker")
@click.option("--force", is_flag=True, default=False, help="Rebuild even if profile exists.")
def profile_build(ticker: str, force: bool) -> None:
    """Parse and analyze all evidence for TICKER and save a CompanyProfile.

    Reads from repositories/TICKER/, writes profile to repositories/TICKER/profile.json.
    """
    from pathlib import Path

    from atlas.acquisition.repository import Repository
    from atlas.analysis.registry import analyze, supported_kinds
    from atlas.company.builder import build_profile
    from atlas.company.store import CompanyStore
    from atlas.knowledge.base import KnowledgeBase

    ticker = ticker.upper()
    atlas = Atlas.from_environment()
    repo_root = atlas.settings.repository_base_path / ticker

    if not repo_root.exists():
        click.echo(
            f"No repository for '{ticker}'. Run: atlas repository build {ticker}",
            err=True,
        )
        raise SystemExit(1)

    profile_path = repo_root / "profile.json"
    if profile_path.exists() and not force:
        click.echo(
            f"Profile already exists at {profile_path}. Use --force to rebuild.",
            err=True,
        )
        raise SystemExit(1)

    click.echo(f"Atlas — Building profile for {ticker}\n")

    repo = Repository(repo_root)
    kb = KnowledgeBase(repo_root)
    supported = set(supported_kinds())

    entries = repo.list_evidence()
    click.echo(f"  Catalog: {len(entries)} entries")

    results = []
    parsed = failed_parse = failed_analyze = skipped_kind = 0

    for entry in entries:
        if entry.kind not in supported:
            skipped_kind += 1
            continue
        if not entry.local_path:
            failed_parse += 1
            continue

        doc = kb.parse(entry)
        if doc.status != "ok":
            failed_parse += 1
            continue
        parsed += 1

        try:
            result = analyze(entry.evidence_id, kb)
            results.append(result)
        except Exception as exc:
            click.echo(f"  ! analyze failed for {entry.evidence_id}: {exc}", err=True)
            failed_analyze += 1

    click.echo(f"  Parsed:  {parsed}")
    click.echo(f"  Analyzed: {len(results)}")
    if failed_parse:
        click.echo(f"  Parse failures: {failed_parse}", err=True)
    if failed_analyze:
        click.echo(f"  Analyze failures: {failed_analyze}", err=True)
    if skipped_kind:
        click.echo(f"  Skipped (unsupported kind): {skipped_kind}")

    if not results:
        click.echo("No results to build a profile from.", err=True)
        raise SystemExit(1)

    built = build_profile(ticker, results)
    store = CompanyStore(profile_path, ticker)
    store.save(built, results)
    click.echo(f"\nProfile saved to {profile_path}")


# ---------------------------------------------------------------------------
# query commands
# ---------------------------------------------------------------------------


@cli.command("query")
@click.argument("ticker")
@click.argument("query_name", metavar="QUERY")
@click.option("--basis", default="consolidated", show_default=True, help="Balance sheet basis.")
@click.option("--keyword", default=None, help="Keyword filter (strategy query only).")
@click.option("--last-n", default=8, show_default=True, help="Quarters to show (ownership query).")
def query_cmd(
    ticker: str,
    query_name: str,
    basis: str,
    keyword: str | None,
    last_n: int,
) -> None:
    """Run an investor query on TICKER's profile.

    Available queries: revenue, capital, strategy, acquisitions, ownership,
    leverage, ratings, risks.

    Examples:

      atlas query TCS revenue

      atlas query TCS strategy --keyword ai

      atlas query TCS ownership --last-n 4
    """
    from pathlib import Path

    from atlas.company.store import CompanyStore

    ticker = ticker.upper()
    atlas = Atlas.from_environment()
    repo_root = atlas.settings.repository_base_path / ticker
    profile_path = repo_root / "profile.json"

    if not profile_path.exists():
        click.echo(
            f"No profile for '{ticker}'. Run: atlas profile build {ticker}",
            err=True,
        )
        raise SystemExit(1)

    store = CompanyStore(profile_path, ticker)
    prof = store.load()

    kwargs: dict[str, object] = {}
    if query_name in ("revenue", "leverage"):
        kwargs["basis"] = basis
    if query_name == "strategy" and keyword:
        kwargs["keyword"] = keyword
    if query_name == "ownership":
        kwargs["last_n"] = last_n

    try:
        result = run_query(query_name, prof, **kwargs)
    except ValueError as exc:
        click.echo(str(exc), err=True)
        click.echo(f"\nAvailable queries: {', '.join(available_queries())}", err=True)
        raise SystemExit(1)

    click.echo(render_result(result))
