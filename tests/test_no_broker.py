"""Paper-only guarantee (IMPLEMENTATION_PLAN.md §10). These must never be relaxed."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

BANNED_PKGS = ["kiteconnect", "upstox", "dhanhq", "growwapi", "smartapi", "alpaca", "ib-insync",
               "ib_insync", "fyers", "breeze-connect", "breeze_connect", "5paisa", "py5paisa"]
BANNED_HOSTS = re.compile(
    r"api\.kite\.trade|kite\.zerodha\.com/connect|api\.upstox\.com|api\.dhan\.co|api\.groww\.in|"
    r"mcp\.groww\.in|apiconnect\.angelbroking|smartapi\.angelbroking|alpaca\.markets|"
    r"api\.fyers\.in|api\.icicidirect|openapi\.5paisa", re.I)


def _our_files():
    for base in ("backend", "web"):
        d = ROOT / base
        if d.exists():
            yield from (f for f in d.rglob("*") if f.is_file() and f.suffix in
                        {".py", ".ts", ".tsx", ".js", ".json", ".yaml", ".yml", ".toml"}
                        and not {"node_modules", "dist", ".venv"} & set(f.parts))


def test_no_broker_packages_in_frontend():
    import json
    pkg = ROOT / "web" / "package.json"
    if pkg.exists():
        deps = json.loads(pkg.read_text())
        names = " ".join({**deps.get("dependencies", {}), **deps.get("devDependencies", {})}).lower()
        assert not [p for p in BANNED_PKGS if p in names]


def test_no_broker_packages_in_dependencies():
    deps = (ROOT / "pyproject.toml").read_text().lower()
    lock = ROOT / "uv.lock"
    if lock.exists():
        deps += lock.read_text().lower()
    hits = [p for p in BANNED_PKGS if re.search(rf'name = "{re.escape(p)}|"{re.escape(p)}[>=<"]', deps)]
    assert not hits, hits


def test_no_broker_hosts_in_our_code():
    hits = [str(f.relative_to(ROOT)) for f in _our_files() if BANNED_HOSTS.search(f.read_text(errors="ignore"))]
    assert not hits, hits


def test_no_broker_imports_in_our_code():
    pat = re.compile(r"^\s*(import|from)\s+(" + "|".join(re.escape(p.replace("-", "_")) for p in BANNED_PKGS) + r")\b", re.M)
    hits = [str(f.relative_to(ROOT)) for f in _our_files() if f.suffix == ".py" and pat.search(f.read_text())]
    assert not hits, hits


def test_simulated_exchange_is_the_only_gateway():
    import backend.api.app  # noqa: F401  load everything the running app loads
    from backend.sim.gateway import OrderGateway

    def all_subclasses(c):
        return set(c.__subclasses__()).union(*(all_subclasses(s) for s in c.__subclasses__()))

    assert {c.__name__ for c in all_subclasses(OrderGateway)} == {"SimulatedExchange"}
    assert all(c.paper for c in all_subclasses(OrderGateway))


def test_vendored_repos_are_untouched():
    """The upstream code must stay exactly as pinned (licence and behaviour preserved)."""
    import subprocess
    for sub in ("vendor/nse-trader-skill", "vendor/claude-trading-skills-india"):
        out = subprocess.run(["git", "-C", str(ROOT / sub), "status", "--porcelain"],
                             capture_output=True, text=True, check=True).stdout
        changed = [l for l in out.splitlines() if not l.endswith("__pycache__/")]
        assert not changed, f"{sub} modified: {changed}"
        assert (ROOT / sub / "LICENSE").is_file()
