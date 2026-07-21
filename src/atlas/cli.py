import sys

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


def _force_utf8_output() -> None:
    """Make stdout/stderr encode UTF-8 so output never dies on a character.

    Windows consoles default to a legacy code page (cp1252) that can't encode
    ₹, €, £, ✓, α, CJK, etc. Any answer containing one would otherwise crash at
    ``click.echo`` time with a UnicodeEncodeError — a provider-independent
    failure any evidence set could trigger. ``errors="replace"`` is a last-resort
    guard for a stream that still can't render a glyph. Streams that predate
    ``reconfigure`` (or test doubles without it) are left untouched.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


@click.group()
def cli() -> None:
    """Atlas — investment research platform."""
    _force_utf8_output()


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
    if report.classified:
        click.echo(f"  Classified:      {report.classified}  ({report.reclassified} reclassified)")
    if report.ocr_used:
        click.echo(f"  OCR used:        {report.ocr_used}")
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
@click.argument("query_arg", required=False, metavar="[METRIC|EVIDENCE_ID]")
@click.option("--basis", default="consolidated", show_default=True, help="Balance sheet basis.")
@click.option("--period-type", default=None, help="Filter to 'quarterly' or 'annual' (timeline/compare).")
@click.option("--keyword", default=None, help="Keyword filter (strategy query only).")
@click.option("--last-n", default=8, show_default=True, help="Quarters to show (ownership query).")
@click.option("-n", "compare_n", default=2, show_default=True, help="Periods to show (compare query).")
def query_cmd(
    ticker: str,
    query_name: str,
    query_arg: str | None,
    basis: str,
    period_type: str | None,
    keyword: str | None,
    last_n: int,
    compare_n: int,
) -> None:
    """Run an investor query on TICKER's profile.

    Available queries: revenue, capital, strategy, acquisitions, ownership,
    leverage, ratings, risks, summary, timeline, compare, drilldown.

    timeline/compare take a METRIC key (run 'atlas metrics' to list all);
    drilldown takes an EVIDENCE_ID (see the Sources column in any table).

    Examples:

      atlas query TCS revenue

      atlas query TCS summary

      atlas query TCS timeline gross_npa_ratio

      atlas query TCS compare operating_margin -n 3

      atlas query TCS drilldown bse-news-7ff81737-8eeb-4f5a-afad-f5f79b216e83

      atlas query TCS strategy --keyword ai
    """
    from pathlib import Path

    from atlas.acquisition.repository import Repository
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
    repo = Repository(repo_root)

    kwargs: dict[str, object] = {}
    if query_name in ("revenue", "leverage"):
        kwargs["basis"] = basis
    if query_name == "strategy" and keyword:
        kwargs["keyword"] = keyword
    if query_name == "ownership":
        kwargs["last_n"] = last_n
    if query_name in ("timeline", "compare"):
        if not query_arg:
            click.echo(f"'{query_name}' requires a metric argument. Run: atlas metrics", err=True)
            raise SystemExit(1)
        kwargs["metric"] = query_arg
        kwargs["basis"] = basis
        if period_type:
            kwargs["period_type"] = period_type
        if query_name == "compare":
            kwargs["n"] = compare_n
        kwargs["repo"] = repo
    if query_name == "drilldown":
        if not query_arg:
            click.echo("'drilldown' requires an evidence_id argument.", err=True)
            raise SystemExit(1)
        kwargs["evidence_id"] = query_arg
        kwargs["repo"] = repo
    if query_name == "summary":
        kwargs["repo"] = repo

    try:
        result = run_query(query_name, prof, **kwargs)
    except ValueError as exc:
        click.echo(str(exc), err=True)
        click.echo(f"\nAvailable queries: {', '.join(available_queries())}", err=True)
        raise SystemExit(1)

    click.echo(render_result(result))


@cli.command("screen")
@click.argument("metric")
@click.argument("op", required=False)
@click.argument("threshold", required=False, type=float)
@click.option("--basis", default="consolidated", show_default=True, help="Balance sheet basis.")
@click.option("--period-type", default=None, help="Filter to 'quarterly' or 'annual'.")
def screen_cmd(
    metric: str,
    op: str | None,
    threshold: float | None,
    basis: str,
    period_type: str | None,
) -> None:
    """Rank every company with a saved profile by METRIC, optionally filtered.

    Cross-company - the one query with no single ticker. Loads every
    repository under the configured base path that has a profile.json.

    Examples:

      atlas screen operating_margin

      atlas screen gross_npa_ratio "<" 2.0

      atlas screen promoter_pledged_pct ">" 0
    """
    from atlas.query import screen as screen_mod

    atlas = Atlas.from_environment()
    profiles = screen_mod.discover_companies(atlas.settings.repository_base_path)

    if not profiles:
        click.echo(
            f"No company profiles found under {atlas.settings.repository_base_path}. "
            "Run: atlas profile build <TICKER>",
            err=True,
        )
        raise SystemExit(1)

    kwargs: dict[str, object] = {"basis": basis}
    if period_type:
        kwargs["period_type"] = period_type
    if op is not None:
        kwargs["op"] = op
    if threshold is not None:
        kwargs["threshold"] = threshold
    kwargs["repos"] = screen_mod.discover_repos(atlas.settings.repository_base_path)

    try:
        result = screen_mod.screen(profiles, metric, **kwargs)
    except ValueError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)

    click.echo(render_result(result))


@cli.command("metrics")
@click.option("--domain", default=None, help="Filter to 'financial', 'esg', or 'ownership'.")
def metrics_cmd(domain: str | None) -> None:
    """List every metric key available to 'timeline', 'compare', and 'screen'."""
    from atlas.query import metrics as metrics_mod

    by_domain = metrics_mod.metrics_by_domain()
    domains = [domain] if domain else ["financial", "esg", "ownership"]

    for d in domains:
        specs = by_domain.get(d, [])
        if not specs:
            continue
        click.echo(f"\n{d.upper()} ({len(specs)})")
        click.echo("-" * (len(d) + len(str(len(specs))) + 3))
        for spec in specs:
            unit_label = spec.unit.value if spec.unit else "-"
            click.echo(f"  {spec.key:<28} {spec.label:<45} [{unit_label}]")


@cli.command("research")
@click.argument("ticker")
@click.option(
    "--out", "out_path", default=None, type=click.Path(dir_okay=False, path_type=None),
    help="Write the report to this file instead of stdout.",
)
def research_cmd(ticker: str, out_path: str | None) -> None:
    """Generate a deterministic, evidence-first research briefing for TICKER.

    Reads the saved CompanyProfile (run 'atlas profile build TICKER' first)
    and every other company's profile under the same repository base (used
    for the Competitive Position section). No LLM, no network access — pure
    assembly of facts and citations Atlas already extracted.
    """
    from pathlib import Path

    from atlas.acquisition.repository import Repository
    from atlas.company.store import CompanyStore
    from atlas.query import screen as screen_mod
    from atlas.research.report import generate_report_markdown

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

    profile = CompanyStore(profile_path, ticker).load()
    repo = Repository(repo_root) if (repo_root / "catalog.json").exists() else None
    peer_profiles = screen_mod.discover_companies(atlas.settings.repository_base_path)

    markdown = generate_report_markdown(ticker, profile, repo, peer_profiles=peer_profiles)

    if out_path:
        Path(out_path).write_text(markdown, encoding="utf-8")
        click.echo(f"Report written to {out_path}")
    else:
        click.echo(markdown)


@cli.command("ask")
@click.argument("ticker")
@click.argument("question")
@click.option(
    "--show-evidence", is_flag=True, default=False,
    help="Print the retrieved source excerpt behind each citation (drill-to-source).",
)
@click.option(
    "--question-retrieval", "question_retrieval", is_flag=True, default=False,
    help=(
        "Merge additional passages relevant to the QUESTION itself (not just "
        "existing claims) into the grounding context, at zero extra KB reads "
        "beyond what --show-evidence hydration already fetches (M1.5, default off "
        "pending eval-measured activation; see ADR-M1.5)."
    ),
)
@click.option(
    "--retrieval-plan", "retrieval_plan", is_flag=True, default=False,
    help=(
        "Plan retrieval before running it: classify the question's intent and "
        "bias passage ranking by doc-type/date/period preferences (M1.7). "
        "Requires --question-retrieval; default off pending eval-measured lift "
        "over the M1.5 baseline — see ADR-M1.7."
    ),
)
@click.option(
    "--explain-plan", "explain_plan", is_flag=True, default=False,
    help="Print the retrieval plan's decision trace (requires --retrieval-plan).",
)
def ask_cmd(
    ticker: str, question: str, show_evidence: bool,
    question_retrieval: bool, retrieval_plan: bool, explain_plan: bool,
) -> None:
    """Answer a natural-language QUESTION about TICKER, grounded in its evidence.

    Reads the saved CompanyProfile (run 'atlas profile build TICKER' first) and
    reasons over it with the LLM configured via ATLAS_LLM_PROVIDER (default
    "anthropic") and its credential (e.g. ATLAS_ANTHROPIC_API_KEY). Every claim
    is grounded in evidence Atlas already extracted; out-of-scope questions
    (e.g. valuation) are declined rather than guessed. When the company's
    KnowledgeBase is present, claim evidence is hydrated with retrieved source
    excerpts (M1); pass --show-evidence to see them, and --question-retrieval
    to also surface passages relevant to this question. --retrieval-plan (M1.7)
    additionally plans that retrieval — classifying intent and biasing ranking
    by doc type/date/period — before it runs.
    """
    from atlas.company.store import CompanyStore
    from atlas.knowledge.base import KnowledgeBase
    from atlas.reasoning.ask import ask
    from atlas.reasoning.context import build_context
    from atlas.reasoning.contracts import Question, SubjectRef
    from atlas.reasoning.llm import (
        LLMConfigurationError,
        LLMTransportError,
        build_llm_client,
    )
    from atlas.reasoning.planner import plan_retrieval
    from atlas.reasoning.render import format_answer, to_answer

    ticker = ticker.upper()
    atlas = Atlas.from_environment()
    repo_root = atlas.settings.repository_base_path / ticker
    profile_path = repo_root / "profile.json"
    if not profile_path.exists():
        click.echo(f"No profile for '{ticker}'. Run: atlas profile build {ticker}", err=True)
        raise SystemExit(1)

    try:
        client = build_llm_client(atlas.settings, role="reasoning")
    except LLMConfigurationError as exc:
        # Any build-time config gap (missing API key, missing Ollama model, ...).
        click.echo(str(exc), err=True)
        raise SystemExit(1)

    profile = CompanyStore(profile_path, ticker).load()
    subject = SubjectRef(subject_id=ticker, display=ticker)
    # M1: hydrate claim evidence with retrieved excerpts when a KnowledgeBase is
    # present. The known_ids identity filter stays a deliberately separate scope
    # boundary — wiring it here could drop claims whose source documents predate
    # the KB, a behavior change beyond what M1 asked for.
    kb = KnowledgeBase(repo_root) if (repo_root / "knowledge.db").exists() else None
    # M1.5 (ADR-M1.5): question-conditioned passage merge, default OFF — the ADR
    # gates activation on eval-measured lift, not on availability alone.
    # M1.7 (ADR-M1.7): --retrieval-plan additionally plans that merge, default
    # OFF for the same reason. Planning without question-retrieval is a no-op
    # (nothing would consume the plan), so it's silently ignored rather than
    # erroring — a flag ordering slip shouldn't fail the whole command.
    plan = plan_retrieval(question) if (question_retrieval and retrieval_plan) else None
    context = build_context(
        profile, subject, kb=kb,
        question=question if question_retrieval else None,
        plan=plan,
    )
    if explain_plan and plan is not None:
        click.echo("Retrieval plan:")
        click.echo(f"  intent: {plan.intent}")
        click.echo(f"  top_k: {plan.top_k}")
        for decision in plan.decisions:
            click.echo(f"  - [{decision.rule}] {decision.input!r} -> {decision.output!r}")
    try:
        result = ask(Question(raw_text=question, subject_ref=subject), context, client)
    except LLMTransportError as exc:
        # Any transport unreachable at call time (Ollama, OmniRoute, ...) — a
        # friendly "is it running?" beats a raw ConnectionError traceback.
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    click.echo(format_answer(to_answer(result, context=context), show_evidence=show_evidence))


@cli.group("eval")
def eval_group() -> None:
    """Evaluate Atlas against the V2.1 acceptance suite (§8)."""


@eval_group.command("run")
@click.option("--milestone", required=True, help="Label for this run, e.g. 'M0'.")
@click.option("--suite", "suite", default="full",
              help="Named preset (core/grounding/refusals/full) or a custom suite "
                   "JSON path. Defaults to 'full' (the bundled §8.6 set).")
@click.option("--capabilities", default="single_name",
              help="Comma-separated capabilities available at this milestone.")
@click.option("--no-judge", "no_judge", is_flag=True, default=False,
              help="Skip the subjective LLM judge (deterministic dimensions only).")
@click.option("--judge-sample", "judge_sample", default=None,
              help="Judge only a subset of active cases: an integer N (N cases chosen "
                   "by deterministic hash rank, not suite order) or a comma-separated "
                   "list of case ids. Deterministic scoring still runs for every case "
                   "regardless.")
@click.option("--no-cache", "no_cache", is_flag=True, default=False,
              help="Disable the LLM-response cache (always call the LLM live).")
@click.option("--cache-path", "cache_path", default=None, type=click.Path(file_okay=False),
              help="Cache directory (defaults to .eval_cache/). Holds separate "
                   "reasoning.json / judge.json files.")
@click.option("--out", "out_path", default=None, type=click.Path(dir_okay=False),
              help="Report path (defaults to eval_reports/<milestone>.json).")
@click.option("--strategy", "strategy_name", type=click.Choice(["baseline", "planned"]), default=None,
              help="Retrieval strategy (M1.8): 'baseline' (a null SearchPlan -- see "
                   "eval/strategies.py) or 'planned' (HeuristicPlanner). Overrides the "
                   "--capabilities question_retrieval/retrieval_plan gating: the case's "
                   "question is always forwarded and the strategy always builds a plan, "
                   "so both strategies get identical retrieval diagnostics. Omit to use "
                   "the pre-M1.8 capability-gated behavior unchanged.")
@click.option("--retrieval-only", "retrieval_only", is_flag=True, default=False,
              help="Score ONLY retrieval/planner metrics -- no LLM call at all, no LLM "
                   "client built (M1.8). Mutually exclusive with --with-answers.")
@click.option("--with-answers", "with_answers", is_flag=True, default=False,
              help="Explicitly run end-to-end reasoning (M1.8) -- the default when "
                   "neither this nor --retrieval-only is given; names the intent at the "
                   "call site. Mutually exclusive with --retrieval-only.")
def eval_run_cmd(
    milestone: str, suite: str, capabilities: str,
    no_judge: bool, judge_sample: str | None,
    no_cache: bool, cache_path: str | None, out_path: str | None,
    strategy_name: str | None, retrieval_only: bool, with_answers: bool,
) -> None:
    """Run the evaluation suite and write a machine-readable report."""
    import dataclasses
    from pathlib import Path

    from atlas.eval.cache import EvalCache
    from atlas.eval.cases import resolve_suite
    from atlas.eval.judge import Judge
    from atlas.eval.runner import LiveReasoningRunner, run_suite
    from atlas.eval.strategies import STRATEGIES
    from atlas.reasoning.llm import LLMConfigurationError, build_llm_client

    if retrieval_only and with_answers:
        click.echo("--retrieval-only and --with-answers are mutually exclusive.", err=True)
        raise SystemExit(1)

    strategy = STRATEGIES[strategy_name] if strategy_name else None

    atlas = Atlas.from_environment()
    # M1.8 (ADR-0004): --retrieval-only builds NO LLM client at all -- not a
    # client that simply goes unused, but one that is never constructed,
    # since retrieval/planner metrics need no LLM whatsoever.
    client = None
    if not retrieval_only:
        try:
            client = build_llm_client(atlas.settings, role="reasoning")
        except LLMConfigurationError as exc:
            click.echo(str(exc), err=True)
            raise SystemExit(1)

    # Free-tier operation: minimize LLM calls by memoizing every (model,
    # fingerprint, prompt, context) completion across separate `atlas eval
    # run` invocations. Enabled by default since that is the point of this
    # mode; --no-cache opts back into always-live calls for a genuinely fresh
    # run. Reasoning and judge each get their own cache file so one role's
    # cache can be inspected or cleared independently of the other, even
    # though a prompt-text collision between the two is not realistically
    # possible (their system prompts are always textually distinct).
    reasoning_cache = judge_cache = None
    if not no_cache and not retrieval_only:
        cache_dir = Path(cache_path) if cache_path else Path(".eval_cache")
        reasoning_cache = EvalCache(cache_dir / "reasoning.json")
        judge_cache = EvalCache(cache_dir / "judge.json")

    # Generation settings aren't visible in a bare (system, user) pair, so a
    # future drift in temperature/max_tokens can't silently produce a false
    # cache hit — it's folded into the key alongside the prompt/context hashes.
    fingerprint = f"t={atlas.settings.llm_temperature}:m={atlas.settings.llm_max_tokens}"

    # §12.6 amendment 1: the judge gets its OWN, independently resolved client
    # (provider AND model) — upgrading the reasoning model/provider never moves
    # the instrument. Independent providers per role (goal 7) means judge
    # construction can now fail on its own (e.g. an unimplemented transport),
    # so it gets the same clean-error treatment as the reasoning client above.
    # M1.8: retrieval-only never builds a judge either -- same "no LLM at all" rule.
    judge = None
    if not no_judge and not retrieval_only:
        try:
            judge_client = build_llm_client(atlas.settings, role="judge")
        except LLMConfigurationError as exc:
            click.echo(str(exc), err=True)
            raise SystemExit(1)
        judge = Judge(
            judge_client, cache=judge_cache, model=atlas.settings.judge_model,
            fingerprint=fingerprint,
        )

    try:
        cases = resolve_suite(suite)
    except FileNotFoundError:
        click.echo(f"Unknown suite '{suite}' (not a preset and not a file).", err=True)
        raise SystemExit(1)

    caps = [c.strip() for c in capabilities.split(",") if c.strip()]
    report = run_suite(
        cases,
        # M1.5: forwarding the same capability set lets --capabilities include
        # "question_retrieval" to toggle the ADR-M1.5 pass for `eval compare`
        # measurement, without gating any case's availability (no case
        # requires it — it's a runner-mode switch, not a case gate).
        LiveReasoningRunner(
            atlas.settings, client, capabilities=frozenset(caps),
            cache=reasoning_cache, fingerprint=fingerprint,
            strategy=strategy, retrieval_only=retrieval_only,
        ),
        judge,
        caps,
        milestone=milestone,
        model=atlas.settings.reasoning_model,
        judge_model=None if (no_judge or retrieval_only) else atlas.settings.judge_model,
        judge_sample=judge_sample,
    )
    if reasoning_cache is not None and judge_cache is not None:
        reasoning_cache.save()
        judge_cache.save()
        report = dataclasses.replace(
            report,
            cache_hits=reasoning_cache.hits + judge_cache.hits,
            cache_misses=reasoning_cache.misses + judge_cache.misses,
        )

    out = Path(out_path) if out_path else Path("eval_reports") / f"{milestone}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.to_json(), encoding="utf-8")

    agg = report.to_dict()["aggregates"]
    click.echo(f"\nEvaluation: {milestone}")
    click.echo(f"  coverage:              {agg['coverage']} ({agg['active_cases']}/{agg['total_cases']} active)")
    if not retrieval_only:
        click.echo(f"  correctness pass rate: {agg['correctness_pass_rate']}")
        click.echo(f"  grounding pass rate:   {agg['grounding_pass_rate']}")
        click.echo(f"  mean reasoning quality:{agg['mean_reasoning_quality']}")
        click.echo(f"  mean usefulness:       {agg['mean_usefulness']}")
        click.echo(f"  refusal rate:          {agg['refusal_rate']}")
    click.echo(f"  errors:                {agg['errors']}")
    if agg.get("planner") is not None:
        click.echo(f"  planner dead rules:    {agg['planner']['dead_rules'] or 'none'}")
    if agg.get("retrieval") is not None:
        click.echo(f"  mean metadata coverage:{agg['retrieval']['mean_metadata_coverage']}")
    if reasoning_cache is not None and judge_cache is not None:
        click.echo(
            f"  cache:                 {reasoning_cache.hits + judge_cache.hits} hits, "
            f"{reasoning_cache.misses + judge_cache.misses} misses"
        )
    click.echo(f"\nReport written to {out}")


@eval_group.command("compare")
@click.argument("baseline", type=click.Path(exists=True, dir_okay=False))
@click.argument("candidate", type=click.Path(exists=True, dir_okay=False))
def eval_compare_cmd(baseline: str, candidate: str) -> None:
    """Diff two evaluation reports (per-dimension deltas, regressions)."""
    import json as _json
    from pathlib import Path

    from atlas.eval.report import Report, compare

    b = Report.from_json(Path(baseline).read_text(encoding="utf-8"))
    c = Report.from_json(Path(candidate).read_text(encoding="utf-8"))
    diff = compare(b, c)

    click.echo(f"\n{diff['baseline']} -> {diff['candidate']}")
    for dim, vals in diff["dimensions"].items():
        click.echo(f"  {dim:<24} {vals['baseline']} -> {vals['candidate']} (delta {vals['delta']})")
    click.echo(f"  newly active: {diff['newly_active'] or 'none'}")
    click.echo(f"  regressions:  {diff['regressions'] or 'none'}")
    click.echo("\n" + _json.dumps(diff, indent=2))


@eval_group.command("compare-retrieval")
@click.argument("baseline", type=click.Path(exists=True, dir_okay=False))
@click.argument("candidate", type=click.Path(exists=True, dir_okay=False))
@click.option("--out", "out_path", default=None, type=click.Path(dir_okay=False),
              help="Write the full comparison (ranking change, retrieval/planner "
                   "deltas, per-case side-by-side, and the advisory recommendation) "
                   "as JSON to this path.")
def eval_compare_retrieval_cmd(baseline: str, candidate: str, out_path: str | None) -> None:
    """Compare BASELINE vs CANDIDATE retrieval strategies (M1.8, ADR-0004):
    ranking change, retrieval/planner deltas, and an advisory SAFE_TO_ENABLE /
    NOT_READY / INSUFFICIENT_DATA recommendation for enabling retrieval
    planning by default. The recommendation is advisory only (Phase 1) --
    this command always exits 0 regardless of the verdict.
    """
    import dataclasses
    import json as _json
    from pathlib import Path

    from atlas.eval.comparison import compare_retrieval
    from atlas.eval.recommendation import recommend
    from atlas.eval.report import Report

    b = Report.from_json(Path(baseline).read_text(encoding="utf-8"))
    c = Report.from_json(Path(candidate).read_text(encoding="utf-8"))
    result = compare_retrieval(b, c)
    rec = recommend(b, c)

    click.echo(f"\n{result['baseline']} -> {result['candidate']}")
    rc = result["ranking_change"]
    click.echo(f"  cases compared:          {rc['cases_compared']}")
    click.echo(f"  mean jaccard overlap:    {rc['mean_jaccard_overlap']}")
    click.echo(f"  cases with changed top1: {rc['cases_with_changed_top1']}")
    rd = result["retrieval_deltas"]
    click.echo(f"  candidates considered Δ: {rd['delta_mean_candidates_considered']}")
    click.echo(f"  metadata coverage Δ:     {rd['delta_mean_metadata_coverage']}")
    click.echo(f"  boost share Δ:           {rd['delta_mean_boost_share']}")

    click.echo(f"\n  recommendation: {rec.verdict}")
    for reason in rec.reasons:
        click.echo(f"    - {reason}")

    if out_path:
        payload = {
            "baseline": result["baseline"], "candidate": result["candidate"],
            "end_to_end": result["end_to_end"],
            "ranking_change": result["ranking_change"],
            "retrieval_deltas": result["retrieval_deltas"],
            "planner_attribution": result["planner_attribution"],
            "side_by_side": [dataclasses.asdict(row) for row in result["side_by_side"]],
            "recommendation": {
                "verdict": rec.verdict, "reasons": list(rec.reasons), "criteria": rec.criteria,
            },
        }
        Path(out_path).write_text(_json.dumps(payload, indent=2), encoding="utf-8")
        click.echo(f"\nFull comparison written to {out_path}")


@eval_group.command("coverage")
@click.option("--suite", "suite", default="full",
              help="Named preset (core/grounding/refusals/full) or a custom suite "
                   "JSON path. Defaults to 'full'.")
@click.option("--format", "output_format", type=click.Choice(["summary", "json"]), default="summary",
              help="'summary' prints a human-readable digest; 'json' prints the full "
                   "BenchmarkCoverage payload. --out (below) always writes JSON "
                   "regardless of this choice.")
@click.option("--out", "out_path", default=None, type=click.Path(dir_okay=False),
              help="Also write the full BenchmarkCoverage payload as JSON to this path.")
def eval_coverage_cmd(suite: str, output_format: str, out_path: str | None) -> None:
    """Static benchmark coverage analysis (M1.8.5, ADR-0005): does the suite
    exercise every planner intent, retrieval rule, and retrieval scenario,
    and is the corpus rich enough to back the doc-type boosts the planner
    declares? No LLM call, no retrieval run -- reads the suite and the
    corpus's KnowledgeBase only.
    """
    import dataclasses
    import json as _json
    from pathlib import Path

    from atlas.benchmark.coverage import analyze
    from atlas.eval.cases import resolve_suite

    atlas = Atlas.from_environment()
    try:
        cases = resolve_suite(suite)
    except FileNotFoundError:
        click.echo(f"Unknown suite '{suite}' (not a preset and not a file).", err=True)
        raise SystemExit(1)

    subjects = sorted({c.subject for c in cases})
    result = analyze(cases, repo_root=atlas.settings.repository_base_path, subjects=subjects)
    s = result.suite

    if output_format == "json":
        click.echo(_json.dumps(dataclasses.asdict(result), indent=2))
    else:
        click.echo(f"\nBenchmark coverage: {s.total_cases} cases across {len(subjects)} subject(s) {subjects}")
        click.echo(f"  general-intent share:    {s.general_intent_share}  (floor: <= 0.30)")
        click.echo(f"  max subject share:       {s.max_subject_share}  (floor: <= 0.60)")
        click.echo(f"  intent    missing: {list(s.intent.missing) or 'none'}"
                   f"  underrepresented: {list(s.intent.underrepresented) or 'none'}")
        click.echo(f"  rule      missing: {list(s.rule.missing) or 'none'}"
                   f"  underrepresented: {list(s.rule.underrepresented) or 'none'}")
        click.echo(f"  scenario  missing: {list(s.scenario.missing) or 'none'}"
                   f"  underrepresented: {list(s.scenario.underrepresented) or 'none'}")
        click.echo(f"  redundant pairs (>{s.redundancy.threshold}): {len(s.redundancy.near_duplicate_pairs)}")
        if result.corpus is not None:
            click.echo(f"  structurally dead doc types: {list(result.corpus.structurally_dead_doc_types) or 'none'}")
            for subject, kinds in result.corpus.retrievable_kinds_by_subject:
                click.echo(f"    {subject}: {list(kinds)}")

    if out_path:
        Path(out_path).write_text(_json.dumps(dataclasses.asdict(result), indent=2), encoding="utf-8")
        click.echo(f"\nCoverage report written to {out_path}")


@eval_group.command("validate-cases")
@click.option("--suite", "suite", default="full",
              help="Named preset (core/grounding/refusals/full) or a custom suite "
                   "JSON path. Defaults to 'full'.")
def eval_validate_cases_cmd(suite: str) -> None:
    """Machine-check every case's provenance claim (M1.8.5, ADR-0005): every
    corpus-derived evidence id resolves in the right subject's KnowledgeBase
    with a matching kind, and every corpus-validated-negative case is
    verified absent by actually running retrieval. No LLM call. Exits 1 if
    any case fails -- unlike the M1.8 advisory recommendation, this checks
    factual claims (does this id exist, is this genuinely absent), not an
    unvalidated policy threshold.
    """
    from atlas.benchmark.validation import validate_cases
    from atlas.eval.cases import resolve_suite

    atlas = Atlas.from_environment()
    try:
        cases = resolve_suite(suite)
    except FileNotFoundError:
        click.echo(f"Unknown suite '{suite}' (not a preset and not a file).", err=True)
        raise SystemExit(1)

    report = validate_cases(cases, atlas.settings.repository_base_path)
    click.echo(f"\nProvenance validation: {report.total_cases} case(s) checked")
    if report.passed:
        click.echo("  PASSED -- no issues found")
        return

    click.echo(f"  FAILED -- {len(report.issues)} issue(s):")
    for issue in report.issues:
        click.echo(f"    - {issue.case_id}: [{issue.kind}] {issue.detail}")
    raise SystemExit(1)
