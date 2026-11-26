# SPDX-License-Identifier: Apache-2.0
"""demo/ard/setup.sh (evidencebook-skills#364): shellcheck, and the script run with a temporary HOME and stand-in
commands on PATH (brew, git, go, npm, curl, Goose's tools), so each test sees what the script would install, build or
download, and what it leaves alone when everything is already at its pin."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
SCRIPT = HERE / "setup.sh"
TEXT = SCRIPT.read_text()
PIN = {k: re.search(rf"^{k}=(\S+)$", TEXT, re.M).group(1)
       for k in ("EVIDENCEBOOK_PIN", "CAPSULE_CLI_PIN", "CAPSULE_ENGINE_PIN", "GOOSE_VERSION", "ACP_VERSION")}
CORE_V = f"v0.1.0-main.{PIN['CAPSULE_CLI_PIN'][:8]}"
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
    "curl": 'echo "curl $*" >>"$STUB_LOG"; echo "curl: (6) Could not resolve host" >&2; exit 6',
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
FORMULA = {"gnu-tar": "gtar", "node": "node npm", "rust": "cargo"}
EXTENSIONS = ("developer", "computercontroller", "skills")


def _exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


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
    for name in ("git", "jq", "node", "npm", "gtar", "go", "cargo"):
        _exe(stubs / "templates" / name, STUBS.get(name, "exit 0"))
    for formula, cmds in FORMULA.items():
        (stubs / "templates" / f"formula-{formula}").write_text(cmds)
    for name in ("node", "gtar"):
        _exe(stubs / name, "exit 0")
    (stubs / "goose-version").write_text(PIN["GOOSE_VERSION"] + "\n")

    demo = home / "ard-demo"
    skills = demo / "evidencebook-skills"
    (skills / ".git").mkdir(parents=True)
    (skills / ".git" / "HEAD-stub").write_text(MAIN + "\n")
    (skills / "demo").symlink_to(HERE.parent)  # the checkout's copy of the script is the one under test
    (skills / ".venv" / "bin").mkdir(parents=True)
    # with $STUB_DIR/venv-cut the venv was cut short: no pip and no packages, until pip installs them
    _exe(skills / ".venv" / "bin" / "python", f'''if [ -f "$STUB_DIR/venv-cut" ]; then
  case "$1 ${{2:-}}" in
    "-m pip") echo "venv pip $3" >>"$STUB_LOG"; [ "$3" != --version ] || exit 1; rm -f "$STUB_DIR/venv-cut"; exit 0 ;;
    "- ") exit 1 ;;
  esac
fi
exec {sys.executable} "$@"''')
    for repo, pin in (("evidencebook", "EVIDENCEBOOK_PIN"), ("capsule-cli", "CAPSULE_CLI_PIN"),
                      ("capsule-engine", "CAPSULE_ENGINE_PIN")):
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
    _exe(local_bin / "capsulectl", f'''case "$1" in
  --version) echo "capsulectl {CORE_V} (commit {PIN['CAPSULE_CLI_PIN']})" ;;
  plugin) [ "$2" = ls ] && echo '{{"plugins": [], "refused": []}}' || echo "capsulectl $*" >>"$STUB_LOG" ;;
esac''')
    for name in ("book", "deal"):
        _exe(plugins / f"capsulectl-{name}", f'echo "capsulectl-{name} {CORE_V} (commit {PIN["EVIDENCEBOOK_PIN"]})"')
    (plugins / "standard-history-module").mkdir()
    (plugins / "capsulectl-deal.d").mkdir()

    goose = home / ".config" / "ard-commerce-goose" / "config"
    goose.mkdir(parents=True)
    (goose / "config.yaml").write_text(_config("openai", on=False))

    env = {"HOME": str(home), "PATH": f"{stubs}:/usr/bin:/bin:/usr/sbin:/sbin", "STUB_LOG": str(log),
           "STUB_DIR": str(stubs), "STUB_MAIN": MAIN, "TMPDIR": str(tmp_path)}

    class Mac:
        pass
    m = Mac()
    m.home, m.demo, m.stubs, m.log, m.env, m.goose_config = home, demo, stubs, log, env, goose / "config.yaml"

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
    assert "already installed (v0.1.0-main." in run.stdout and "Goose extensions: already all off" in run.stdout
    assert (f"Set-up is done at evidencebook-skills {MAIN[:7]}, evidencebook {PIN['EVIDENCEBOOK_PIN'][:7]}, capsule-cli "
            f"{PIN['CAPSULE_CLI_PIN'][:7]} (capsulectl {CORE_V}), capsule-engine {PIN['CAPSULE_ENGINE_PIN'][:7]}, Goose "
            f"Desktop {PIN['GOOSE_VERSION']}, model openai.") in run.stdout
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
    head = mac.demo / "capsule-cli" / ".git" / "HEAD-stub"
    head.write_text("b" * 40 + "\n")
    run = mac.run()
    assert run.returncode == 0, run.stdout + run.stderr
    assert f"Moving capsule-cli to {PIN['CAPSULE_CLI_PIN'][:7]} ..." in run.stdout
    assert head.read_text().strip() == PIN["CAPSULE_CLI_PIN"]


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
    assert "  Not yet: no model is chosen in the demo's Goose yet." in run.stdout and "open-windows" not in run.stdout
    # the choice's own check turned the extensions off, and the run says so rather than "already all off"
    assert "Turned off every Goose extension in the demo's Goose." in run.stdout and "already all off" not in run.stdout
    # Goose is quit before its settings are read or written, every time
    assert [c.split()[0] for c in mac.calls() if c.startswith(("open", "osascript"))] == \
        ["open", "osascript", "open", "osascript"]
    assert "Claude Code" not in "".join(c for c in mac.calls() if c.startswith(("npm", "claude", "brew")))
    import yaml
    doc = yaml.safe_load(mac.goose_config.read_text())
    assert doc["active_provider"] == "google" and not any(doc["extensions"][e]["enabled"] for e in EXTENSIONS)
    assert "model google." in run.stdout
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
