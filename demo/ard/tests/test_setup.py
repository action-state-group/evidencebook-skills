# SPDX-License-Identifier: Apache-2.0
"""demo/ard/setup.sh (evidencebook-skills#364): shellcheck, and the script run with a temporary HOME and stand-in
commands on PATH (brew, git, go, npm, curl, Goose's tools), so each test sees what the script would install, build or
download, and what it leaves alone when everything is already at its pin. The curl stand-in serves a stand-in capsulectl
release (real files and a real SHA256SUMS, #435)."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
SCRIPT = HERE / "setup.sh"
TEXT = SCRIPT.read_text()
PIN = {k: re.search(rf"^{k}=(\S+)$", TEXT, re.M).group(1)
       for k in ("CAPSULECTL_VERSION", "EVIDENCEBOOK_PIN", "CAPSULE_CLI_PIN", "CAPSULE_ENGINE_PIN", "GOOSE_VERSION",
                 "ACP_VERSION")}
CORE_V = PIN["CAPSULECTL_VERSION"]
OLD_V, OLD_CLI, OLD_EB = "v0.1.0-main.052a8a6a", "052a8a6a7de4360a9e18b1269ba558bf71d0fef2", "f" * 40  # the pins before #435
ORG = "https://github.com/action-state-group"
MAIN = "a" * 40  # where the stand-in origin/main of evidencebook-skills is

JQ = shutil.which("jq")
pytestmark = pytest.mark.skipif(not JQ or not Path("/bin/bash").exists(), reason="the script needs jq and /bin/bash")

# Each stand-in logs its arguments to $STUB_LOG, one line per call (brew also logs whether it may upgrade anything).
STUBS = {
    "uname": 'case "$1" in -s) echo Darwin ;; -m) echo arm64 ;; *) echo Darwin ;; esac',
    "lsof": "exit 0",
    # Goose runs while $STUB_DIR/running is there: open -a starts it, a quit through osascript ends it
    "pgrep": '[ -f "$STUB_DIR/running" ]',
    "osascript": 'echo "osascript $*" >>"$STUB_LOG"; rm -f "$STUB_DIR/running"',
    # the person's step 8: the demo Goose starts, and the provider is chosen in it on the try $STUB_DIR/choose-on names
    "open": r'''echo "open $1 $2" >>"$STUB_LOG"; touch "$STUB_DIR/running"
n=$(( $(cat "$STUB_DIR/opened" 2>/dev/null || echo 0) + 1 )); echo $n >"$STUB_DIR/opened"
[ "$n" != "$(cat "$STUB_DIR/choose-on" 2>/dev/null)" ] \
  || echo "active_provider: google" >>"$HOME/.config/ard-commerce-goose/config/config.yaml"''',
    "ditto": 'echo "ditto $*" >>"$STUB_LOG"; exit 1',
    # a release file under $STUB_DIR/releases/<repository>/<tag>/ is served; anything else is not reached
    "curl": r'''echo "curl $*" >>"$STUB_LOG"
url=${!#}; out=""; while [ $# -gt 0 ]; do [ "$1" != -o ] || out=$2; shift; done
rel=${url#https://github.com/action-state-group/}; rel=${rel/\/releases\/download\//\/}
if [ "$rel" != "$url" ] && [ -f "$STUB_DIR/releases/$rel" ]; then cp "$STUB_DIR/releases/$rel" "$out"; exit 0; fi
echo "curl: (6) Could not resolve host" >&2; exit 6''',
    "npm": 'echo "npm $*" >>"$STUB_LOG"',
    "plutil": 'cat "$STUB_DIR/goose-version" 2>/dev/null || exit 1',
    "claude": 'echo "claude $*" >>"$STUB_LOG"; [ "$1 $2" = "auth status" ] && echo \'{"loggedIn": true}\'',
    "python3": f'''[ "$1 $2" != "-m venv" ] || {{ echo "python3 $*" >>"$STUB_LOG"; exit 0; }}
exec {sys.executable} "$@"''',
    "jq": f'exec {JQ} "$@"',
    # brew install <formula> puts that formula's stand-in on PATH
    "brew": r'''echo "brew $*" >>"$STUB_LOG"
[ "$1" != install ] || [ "$HOMEBREW_NO_INSTALL_UPGRADE$HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK" = 11 ] \
  || echo "brew may upgrade" >>"$STUB_LOG"
case "$1" in
  --prefix) echo "$STUB_DIR/brew-prefix" ;;
  install) f=${!#}; for c in $(cat "$STUB_DIR/templates/formula-$f" 2>/dev/null || echo "$f"); do
             cp "$STUB_DIR/templates/$c" "$STUB_DIR/$c" 2>/dev/null || printf '#!/bin/bash\nexit 0\n' >"$STUB_DIR/$c"
             chmod +x "$STUB_DIR/$c"; done ;;
esac''',
    "go": r'''echo "go $*" >>"$STUB_LOG"
if [ "$1 $2" = "version -m" ]; then
  [ -f "$3" ] || exit 1
  echo "	build	vcs.revision=$(cat "$3")"; echo "	build	vcs.modified=false"
fi''',
    # a checkout is a folder with .git/HEAD-stub (its commit) and, when it has changes, .git/dirty
    "git": r'''echo "git $*" >>"$STUB_LOG"
if [ "$1" = clone ]; then d=${!#}; mkdir -p "$d/.git"; echo 0000 >"$d/.git/HEAD-stub"; exit 0; fi
[ "$1" = -C ] || exit 0
d=$2; shift 2
case "$1" in
  rev-parse) if [ "$2" = HEAD ]; then cat "$d/.git/HEAD-stub"; elif [ "$2" = --short=7 ]; then cut -c1-7 "$d/.git/HEAD-stub"; else echo "$STUB_MAIN"; fi ;;
  status) cat "$d/.git/dirty" 2>/dev/null; true ;;
  checkout) echo "${!#}" >"$d/.git/HEAD-stub" ;;
esac''',
}
FORMULA = {"node": "node npm", "rust": "cargo", "tmux": "tmux"}
EXTENSIONS = ("developer", "computercontroller", "skills")


def _exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _core(version: str, commit: str) -> str:
    """A capsulectl stand-in: its version, an empty plugin list, and `plugin install`, which copies the plugin into the
    plugin folder, executable (capsule-cli cli/plugin_install.go stages it 0755), under its name without the version
    and platform."""
    return f'''case "$1" in
  --version) echo "capsulectl {version} (commit {commit})" ;;
  plugin) case "$2" in
    ls) echo '{{"plugins": [], "refused": []}}' ;;
    install) echo "capsulectl $*" >>"$STUB_LOG"; n=$(basename "$3"); n=${{n%%-v[0-9]*}}
             install -m 0755 "$3" "$HOME/.local/lib/capsulectl/plugins/$n" ;;
  esac ;;
esac'''


def _plugin(name: str, version: str, commit: str) -> str:
    return f'echo "capsulectl-{name} {version} (commit {commit})"'


def _tgz(top: str) -> bytes:
    """A view tarball: one folder with one file, as the release's standard-history and deal-view tarballs hold."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        d = tarfile.TarInfo(top)
        d.type, d.mode = tarfile.DIRTYPE, 0o755
        tar.addfile(d)
        f = tarfile.TarInfo(f"{top}/view.css")
        f.size = 4
        tar.addfile(f, io.BytesIO(b"x{}\n"))
    return buf.getvalue()


def _release(stubs: Path) -> dict[str, Path]:
    """The stand-in release at the pins: capsule-cli's and evidencebook's, each with its SHA256SUMS; returns each
    file's path by name."""
    v = CORE_V
    files = {
        ("capsule-cli", v): {f"capsulectl-{v}-darwin-arm64": "#!/bin/bash\n" + _core(v, PIN["CAPSULE_CLI_PIN"]) + "\n"},
        ("evidencebook", f"capsulectl/{v}"): {
            **{f"capsulectl-{n}-{v}-darwin-arm64": "#!/bin/bash\n" + _plugin(n, v, PIN["EVIDENCEBOOK_PIN"]) + "\n"
               for n in ("book", "deal")},
            f"standard-history-{v}.tar.gz": _tgz("standard-history-module"),
            f"deal-view-{v}.tar.gz": _tgz("capsulectl-deal.d"),
            f"deal-skill-{v}.tar.gz": _tgz("skills"),  # in the release, not installed
        },
    }
    paths = {}
    for (repo, tag), named in files.items():
        d = stubs / "releases" / repo / tag
        d.mkdir(parents=True)
        sums = []
        for name, body in named.items():
            data = body.encode() if isinstance(body, str) else body
            (d / name).write_bytes(data)
            sums.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
            paths[name] = d / name
        (d / "SHA256SUMS").write_text("\n".join(sums) + "\n")
        paths[f"{repo}/SHA256SUMS"] = d / "SHA256SUMS"
    return paths


def _config(provider: str | None, on: bool) -> str:
    lines = ["extensions:"]
    for name in EXTENSIONS:
        lines += [f"  {name}:", f"    enabled: {'true' if on else 'false'}", "    type: builtin"]
    lines += ["scheduler:", "  enabled: true"]
    if provider:
        lines.append(f"active_provider: {provider}")
    return "\n".join(lines) + "\n"


@pytest.fixture
def mac(tmp_path):
    """A set-up Mac: every tool on PATH, every checkout and build at its pin, the demo Goose on an API-key provider
    with every extension off."""
    home = tmp_path / "home with space"
    stubs = tmp_path / "stubs"
    (stubs / "templates").mkdir(parents=True)
    log = tmp_path / "calls.log"
    log.touch()
    for name, body in STUBS.items():
        _exe(stubs / name, body)
    for name in ("git", "jq", "node", "npm", "tmux", "go", "cargo"):
        _exe(stubs / "templates" / name, STUBS.get(name, "exit 0"))
    for formula, cmds in FORMULA.items():
        (stubs / "templates" / f"formula-{formula}").write_text(cmds)
    for name in ("node", "tmux"):
        _exe(stubs / name, "exit 0")
    (stubs / "goose-version").write_text(PIN["GOOSE_VERSION"] + "\n")

    demo = home / "ard-demo"
    skills = demo / "evidencebook-skills"
    (skills / ".git").mkdir(parents=True)
    (skills / ".git" / "HEAD-stub").write_text(MAIN + "\n")
    (skills / "demo").symlink_to(HERE.parent)  # the checkout's copy of the script is the one under test
    (skills / ".venv" / "bin").mkdir(parents=True)
    # with $STUB_DIR/venv-cut the venv was cut short: no pip and no packages, until pip installs them
    # the witness check (witness_check.py) says $STUB_DIR/witness-out and exits with $STUB_DIR/witness-rc
    _exe(skills / ".venv" / "bin" / "python", f'''case "${{1:-}}" in */witness_check.py)
  echo "witness-check $ARD_EVIDENCEBOOK $CAPSULECTL_DEAL" >>"$STUB_LOG"
  cat "$STUB_DIR/witness-out" 2>/dev/null || echo "Action State's witness took a test stamp."
  exit "$(cat "$STUB_DIR/witness-rc" 2>/dev/null || echo 0)" ;;
esac
if [ -f "$STUB_DIR/venv-cut" ]; then
  case "$1 ${{2:-}}" in
    "-m pip") echo "venv pip $3" >>"$STUB_LOG"; [ "$3" != --version ] || exit 1; rm -f "$STUB_DIR/venv-cut"; exit 0 ;;
    "- ") exit 1 ;;
  esac
fi
exec {sys.executable} "$@"''')
    for repo, pin in (("evidencebook", "EVIDENCEBOOK_PIN"), ("capsule-engine", "CAPSULE_ENGINE_PIN")):
        (demo / repo / ".git").mkdir(parents=True)
        (demo / repo / ".git" / "HEAD-stub").write_text(PIN[pin] + "\n")
    (demo / "bin").mkdir()
    (demo / "bin" / "capsule-engine").write_text(PIN["CAPSULE_ENGINE_PIN"])
    acp = demo / "acp" / "node_modules"
    (acp / "@agentclientprotocol" / "claude-agent-acp").mkdir(parents=True)
    (acp / "@agentclientprotocol" / "claude-agent-acp" / "package.json").write_text(
        json.dumps({"version": PIN["ACP_VERSION"]}))
    (acp / ".bin").mkdir()
    _exe(acp / ".bin" / "claude-agent-acp", "exit 0")

    local_bin, plugins = home / ".local" / "bin", home / ".local" / "lib" / "capsulectl" / "plugins"
    local_bin.mkdir(parents=True)
    plugins.mkdir(parents=True)
    _exe(local_bin / "capsulectl", _core(CORE_V, PIN["CAPSULE_CLI_PIN"]))
    for name in ("book", "deal"):
        _exe(plugins / f"capsulectl-{name}", _plugin(name, CORE_V, PIN["EVIDENCEBOOK_PIN"]))
    (plugins / "standard-history-module").mkdir()
    (plugins / "capsulectl-deal.d").mkdir()

    goose = home / ".config" / "ard-commerce-goose" / "config"
    goose.mkdir(parents=True)
    (goose / "config.yaml").write_text(_config("openai", on=False))

    # The system directories come in as links, without the tools the stand-ins replace: a runner's own go or git in
    # /usr/bin must not make a "missing" tool look installed (evidencebook-skills#365's main run on Linux).
    system = tmp_path / "system"
    system.mkdir()
    replaced = set(STUBS) | {"git", "jq", "node", "npm", "tmux", "go", "cargo"}
    for d in ("/usr/bin", "/bin", "/usr/sbin", "/sbin"):
        for tool in sorted(Path(d).iterdir()) if Path(d).is_dir() else ():
            link = system / tool.name
            if tool.name not in replaced and not link.exists() and not link.is_symlink():
                link.symlink_to(tool)

    env = {"HOME": str(home), "PATH": f"{stubs}:{system}", "STUB_LOG": str(log),
           "STUB_DIR": str(stubs), "STUB_MAIN": MAIN, "TMPDIR": str(tmp_path)}

    class Mac:
        pass
    m = Mac()
    m.home, m.demo, m.stubs, m.log, m.env, m.goose_config = home, demo, stubs, log, env, goose / "config.yaml"
    m.local_bin, m.plugins, m.release = local_bin, plugins, _release(stubs)

    def run(stdin: str | None = None) -> subprocess.CompletedProcess:
        log.write_text("")
        return subprocess.run(["/bin/bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120,
                              input=stdin if stdin is not None else "")
    m.run = run
    m.calls = lambda: log.read_text().splitlines()
    return m


CHANGES = re.compile(r"^(brew install|git clone|git -C \S+ checkout|go build|curl |npm install|osascript|ditto"
                     r"|capsulectl plugin install)")


def test_shellcheck():
    if not shutil.which("shellcheck"):
        pytest.skip("shellcheck is not installed")
    run = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout


def test_a_set_up_mac_is_left_as_it_is(mac):
    before = mac.goose_config.read_bytes()
    run = mac.run()  # no keyboard: if it asked anything, it would stop
    assert run.returncode == 0, run.stdout + run.stderr
    assert [c for c in mac.calls() if CHANGES.match(c)] == []
    # evidencebook-skills follows main, so it is fetched to see where main is; the pinned ones are not even fetched
    assert [c for c in mac.calls() if " fetch" in c] == [f"git -C {mac.demo}/evidencebook-skills fetch -q origin"]
    assert mac.goose_config.read_bytes() == before
    assert "Installing" not in run.stdout and "Building" not in run.stdout
    assert f"already installed ({CORE_V})" in run.stdout and "Goose extensions: already all off" in run.stdout
    assert (f"Set-up is done at evidencebook-skills {MAIN[:7]}, capsulectl {CORE_V} (capsule-cli "
            f"{PIN['CAPSULE_CLI_PIN'][:7]}, evidencebook {PIN['EVIDENCEBOOK_PIN'][:7]}), capsule-engine "
            f"{PIN['CAPSULE_ENGINE_PIN'][:7]}, Goose Desktop {PIN['GOOSE_VERSION']}, provider OpenAI.") in run.stdout
    assert run.stdout.rstrip().endswith('Next: "Before each run" in the RUNBOOK.')
    # the checks of "What you need" are printed once, before the hand-over to the checkout's copy
    assert run.stdout.count("jq: already installed") == 1


def test_a_missing_tool_is_installed_once(mac):
    (mac.stubs / "go").unlink()
    run = mac.run()
    assert run.returncode == 0, run.stdout + run.stderr
    assert "Installing Go with Homebrew (brew install go) ..." in run.stdout
    assert "brew install go" in mac.calls()
    assert "upgrades nothing you have" in run.stdout
    assert "brew may upgrade" not in mac.calls()
    run = mac.run()
    assert run.returncode == 0 and not [c for c in mac.calls() if c.startswith("brew install")]


def test_a_repository_off_its_pin_is_moved(mac):
    head = mac.demo / "evidencebook" / ".git" / "HEAD-stub"
    head.write_text("b" * 40 + "\n")
    run = mac.run()
    assert run.returncode == 0, run.stdout + run.stderr
    assert f"Setting evidencebook to {PIN['EVIDENCEBOOK_PIN'][:7]} ..." in run.stdout
    assert head.read_text().strip() == PIN["EVIDENCEBOOK_PIN"]


# ---- capsulectl from its release (#435) -------------------------------------------------------------------------------
def _downloads(mac) -> list[str]:
    return [c.split()[-1] for c in mac.calls() if c.startswith("curl ") and "/releases/download/" in c]


def _release_urls() -> list[str]:
    cli, eb = f"{ORG}/capsule-cli/releases/download/{CORE_V}", f"{ORG}/evidencebook/releases/download/capsulectl/{CORE_V}"
    return [f"{cli}/SHA256SUMS", f"{cli}/capsulectl-{CORE_V}-darwin-arm64", f"{eb}/SHA256SUMS"] + [
        f"{eb}/{f}" for f in (f"capsulectl-book-{CORE_V}-darwin-arm64", f"capsulectl-deal-{CORE_V}-darwin-arm64",
                              f"standard-history-{CORE_V}.tar.gz", f"deal-view-{CORE_V}.tar.gz")]


def _installed(mac) -> list[str]:
    out = [subprocess.run([str(mac.local_bin / "capsulectl"), "--version"], capture_output=True, text=True).stdout]
    out += [subprocess.run([str(mac.plugins / f"capsulectl-{n}"), "--version"], capture_output=True, text=True).stdout
            for n in ("book", "deal")]
    return [line.strip() for line in out]


def _old_pins(mac) -> None:
    """A Mac set up at the pins before #435: capsulectl and its plugins built from commits, a capsule-cli checkout."""
    _exe(mac.local_bin / "capsulectl", _core(OLD_V, OLD_CLI))
    for n in ("book", "deal"):
        _exe(mac.plugins / f"capsulectl-{n}", _plugin(n, OLD_V, OLD_EB))
    (mac.demo / "capsule-cli" / ".git").mkdir(parents=True)
    (mac.demo / "capsule-cli" / ".git" / "HEAD-stub").write_text(OLD_CLI + "\n")


def test_a_mac_at_the_old_pins_gets_the_release_and_a_rerun_downloads_nothing(mac):
    _old_pins(mac)
    run = mac.run()
    assert run.returncode == 0, run.stdout + run.stderr
    assert f"  Downloading the {CORE_V} release ...\n  Installed {CORE_V}." in run.stdout
    assert _downloads(mac) == _release_urls()  # deal-skill is in the release, not downloaded
    assert _installed(mac) == [f"capsulectl {CORE_V} (commit {PIN['CAPSULE_CLI_PIN']})"] + [
        f"capsulectl-{n} {CORE_V} (commit {PIN['EVIDENCEBOOK_PIN']})" for n in ("book", "deal")]
    assert (mac.plugins / "standard-history-module" / "view.css").is_file()
    assert (mac.plugins / "capsulectl-deal.d" / "view.css").is_file()
    # nothing is built, and capsule-cli's old checkout is neither moved nor needed
    assert not [c for c in mac.calls() if c.startswith("go build") or "capsule-cli" in c and c.startswith("git")]
    run = mac.run()
    assert run.returncode == 0 and _downloads(mac) == [] and f"already installed ({CORE_V})" in run.stdout


def test_a_fresh_mac_gets_the_release(mac):
    shutil.rmtree(mac.home / ".local")
    run = mac.run()
    assert run.returncode == 0, run.stdout + run.stderr
    assert _downloads(mac) == _release_urls()
    assert _installed(mac)[0] == f"capsulectl {CORE_V} (commit {PIN['CAPSULE_CLI_PIN']})"
    assert not (mac.demo / "capsule-cli").exists()


@pytest.mark.parametrize("fault", ["missing", "not-listed", "changed"])
def test_a_release_file_that_does_not_check_out_installs_nothing(mac, fault):
    """A file that cannot be downloaded, that its release's SHA256SUMS does not list, or whose checksum differs stops
    the set-up before anything is installed: the old capsulectl and plugins stay as they were."""
    _old_pins(mac)
    deal = mac.release[f"capsulectl-deal-{CORE_V}-darwin-arm64"]
    if fault == "missing":
        deal.unlink()
    elif fault == "not-listed":
        sums = mac.release["evidencebook/SHA256SUMS"]
        sums.write_text("".join(line for line in sums.read_text().splitlines(True) if deal.name not in line))
    else:
        deal.write_text(deal.read_text() + "# changed\n")
    before = _installed(mac)
    run = mac.run()
    assert run.returncode == 1
    m = re.search(rf"Set-up stopped while downloading the capsulectl {CORE_V} release\.\nThe details are in (\S+);",
                  run.stderr)
    assert m, run.stderr
    details = Path(m.group(1)).read_text()
    assert {"missing": "Could not resolve host", "not-listed": f"{deal.name} is not in",
            "changed": f"{deal.name}: FAILED"}[fault] in details
    assert _installed(mac) == before
    assert not [c for c in mac.calls() if c.startswith("capsulectl plugin install")]
    assert not (mac.plugins / "standard-history-module" / "view.css").exists()


def test_a_checkout_with_changes_of_its_own_is_not_moved(mac):
    (mac.demo / "evidencebook" / ".git" / "HEAD-stub").write_text("b" * 40 + "\n")
    (mac.demo / "evidencebook" / ".git" / "dirty").write_text(" M README.md\n")
    run = mac.run()
    assert run.returncode == 1
    assert "evidencebook has changes of its own" in run.stderr
    assert not [c for c in mac.calls() if " checkout" in c]
    # evidencebook-skills follows main: one with changes of its own is used where it is, not moved
    (mac.demo / "evidencebook" / ".git" / "dirty").unlink()
    (mac.demo / "evidencebook-skills" / ".git" / "HEAD-stub").write_text("b" * 40 + "\n")
    (mac.demo / "evidencebook-skills" / ".git" / "dirty").write_text(" M README.md\n")
    run = mac.run()
    assert run.returncode == 1 and "has changes of its own, so it was not moved" in run.stderr
    assert not [c for c in mac.calls() if " checkout" in c]


def test_a_checkout_at_its_pin_with_changes_of_its_own_is_not_built_from(mac):
    (mac.demo / "evidencebook" / ".git" / "dirty").write_text(" M capsulectl/main.go\n")
    (mac.home / ".local" / "lib" / "capsulectl" / "plugins" / "capsulectl-book").unlink()  # so it would rebuild
    run = mac.run()
    assert run.returncode == 1
    assert "has changes of its own, and the demo is built only from" in run.stderr
    assert not [c for c in mac.calls() if CHANGES.match(c)]


def test_a_python_environment_cut_short_is_made_again(mac):
    (mac.stubs / "venv-cut").touch()
    run = mac.run()
    assert run.returncode == 0, run.stdout + run.stderr
    calls = mac.calls()
    assert calls.index(f"python3 -m venv --clear {mac.demo}/evidencebook-skills/.venv") < calls.index("venv pip install")
    run = mac.run()
    assert run.returncode == 0 and not [c for c in mac.calls() if c.startswith(("python3 -m venv", "venv pip"))]


def test_settings_that_cannot_be_written_stop_plainly(mac):
    mac.goose_config.write_text(_config("openai", on=True))
    mac.goose_config.parent.chmod(0o555)
    try:
        run = mac.run()
    finally:
        mac.goose_config.parent.chmod(0o755)
    assert run.returncode == 1
    assert f"Set-up stopped: {mac.goose_config} could not be written (Permission denied)" in run.stderr
    assert "Traceback" not in run.stderr
    assert [p.name for p in mac.goose_config.parent.iterdir()] == ["config.yaml"]


def test_another_provider_is_chosen_in_goose_with_a_second_try(mac):
    mac.goose_config.write_text(_config(None, on=True))
    (mac.stubs / "choose-on").write_text("2")  # the first time, the person presses Return before choosing
    run = mac.run(stdin="3\n2\n\n\n")
    assert run.returncode == 0, run.stdout + run.stderr
    assert "Pick your provider and follow its screens" in run.stdout
    assert "  Not yet: no model is chosen in the demo's Goose." in run.stdout and "open-windows" not in run.stdout
    # the choice's own check turned the extensions off, and the run says so rather than "already all off"
    assert "Turned off every Goose extension in the demo's Goose." in run.stdout and "already all off" not in run.stdout
    # Goose is quit before its settings are read or written, every time
    assert [c.split()[0] for c in mac.calls() if c.startswith(("open", "osascript"))] == \
        ["open", "osascript", "open", "osascript"]
    assert "Claude Code" not in "".join(c for c in mac.calls() if c.startswith(("npm", "claude", "brew")))
    import yaml
    doc = yaml.safe_load(mac.goose_config.read_text())
    assert doc["active_provider"] == "google" and not any(doc["extensions"][e]["enabled"] for e in EXTENSIONS)
    assert "provider Google." in run.stdout
    after = mac.goose_config.read_bytes()
    run = mac.run()  # and a second run leaves it as it is
    assert run.returncode == 0 and mac.goose_config.read_bytes() == after
    assert not [c for c in mac.calls() if CHANGES.match(c) or c.startswith("open")]


def test_extensions_still_on_are_turned_off_once(mac):
    mac.goose_config.write_text(_config("openai", on=True) + "GOOSE_MODEL: gpt-5\n")
    run = mac.run()
    assert run.returncode == 0, run.stdout + run.stderr
    assert "Turned off every Goose extension in the demo's Goose." in run.stdout
    import yaml
    doc = yaml.safe_load(mac.goose_config.read_text())
    assert all(doc["extensions"][e]["enabled"] is False for e in EXTENSIONS)
    assert doc["scheduler"] == {"enabled": True}
    assert doc["active_provider"] == "openai" and doc["GOOSE_MODEL"] == "gpt-5"
    after = mac.goose_config.read_bytes()
    run = mac.run()
    assert run.returncode == 0 and mac.goose_config.read_bytes() == after


@pytest.mark.parametrize("provider", [None, "claude-code"])
def test_the_model_choice_asks_and_stops_plainly_without_a_keyboard(mac, provider):
    # no provider yet, or one that runs its own agent: the person's step, which needs an answer
    mac.goose_config.write_text(_config(provider, on=False))
    run = mac.run()
    assert run.returncode == 1
    assert "One step is yours: choose the model the demo's Goose windows use." in run.stdout
    assert "Set-up stopped: no answer was typed." in run.stderr
    assert "Traceback" not in run.stderr


def test_claude_code_gets_the_pinned_adapter_and_a_sign_in_check(mac):
    mac.goose_config.write_text(_config("claude-acp", on=False))
    shutil.rmtree(mac.demo / "acp")
    run = mac.run()
    # the stand-in npm installs nothing, so the provider check then names the missing adapter and stops
    assert f"npm install --prefix {mac.demo}/acp @agentclientprotocol/claude-agent-acp@{PIN['ACP_VERSION']}" in mac.calls()
    assert not [c for c in mac.calls() if c.startswith("npm") and " -g" in c]
    assert "claude auth status" in mac.calls()
    assert run.returncode == 1 and "Claude Code adapter is not installed" in run.stderr


def test_a_failed_download_names_the_step_and_keeps_the_details(mac):
    (mac.stubs / "goose-version").write_text("1.58.0\n")
    run = mac.run()
    assert run.returncode == 1
    m = re.search(r"Set-up stopped while downloading and installing Goose Desktop [0-9.]+\.\nThe details are in (\S+);",
                  run.stderr)
    assert m, run.stderr
    assert "Could not resolve host" in Path(m.group(1)).read_text()
    assert "curl:" not in run.stdout + run.stderr.replace(m.group(1), "")


def test_the_script_runs_its_checkouts_copy_with_the_same_arguments(mac):
    run = subprocess.run(["/bin/bash", str(SCRIPT), "--no-such"], env=mac.env, capture_output=True, text=True)
    assert run.returncode == 1 and "unknown option --no-such" in run.stderr
    run = subprocess.run(["/bin/bash", str(SCRIPT), "--real-rail"], env=mac.env, capture_output=True, text=True,
                         input="")
    assert run.returncode == 0, run.stdout + run.stderr
    assert "brew install rust" in mac.calls()


def test_the_witness_takes_a_real_stamp_last(mac):
    """The set-up ends with the witness check (evidencebook-skills#359), run with the demo's pinned checkout and
    capsulectl-deal."""
    run = mac.run()
    assert run.returncode == 0, run.stdout + run.stderr
    assert (f"witness-check {mac.demo}/evidencebook {mac.home}/.local/lib/capsulectl/plugins/capsulectl-deal"
            in mac.calls())
    assert "Action State's witness: one test stamp (it can take up to a minute) ...\n  Action State's witness took a test stamp.\n" in run.stdout


def test_the_testbed_takes_the_witness_check_over(mac):
    """testbed.sh runs the set-up with ARD_SETUP_WITNESS=testbed: a refusing witness does not stop it, since the
    testbed measures the witness next and offers the local one (evidencebook-skills#382)."""
    (mac.stubs / "witness-rc").write_text("1")
    mac.env["ARD_SETUP_WITNESS"] = "testbed"
    run = mac.run()
    assert run.returncode == 0, run.stdout + run.stderr
    assert not any(c.startswith("witness-check") for c in mac.calls())
    assert "Action State's witness: the testbed measures it next." in run.stdout


def test_a_witness_that_takes_no_stamp_stops_the_set_up(mac):
    """A witness whose home page answers but that refuses stamps stops the set-up with the check's own words."""
    (mac.stubs / "witness-out").write_text("Action State's witness answered but refused a test stamp (HTTP 409).\n"
                                           "The details are in /tmp/x.log.\n")
    (mac.stubs / "witness-rc").write_text("1")
    run = mac.run()
    assert run.returncode == 1
    assert "Set-up stopped: Action State's witness answered but refused a test stamp (HTTP 409)." in run.stderr
    assert "The details are in /tmp/x.log." in run.stderr
    assert "Set-up is done" not in run.stdout
