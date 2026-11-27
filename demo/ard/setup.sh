#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Functions passed to run() are invoked through "$@", which shellcheck cannot follow.
# shellcheck disable=SC2329
# Set up the ARD demo on this Mac, once (RUNBOOK.md, "Set up, once"; evidencebook-skills#364).
#
#   f=$(mktemp) && curl -fsSL https://raw.githubusercontent.com/action-state-group/evidencebook-skills/main/demo/ard/setup.sh -o "$f" && /bin/bash "$f"
#   ~/ard-demo/evidencebook-skills/demo/ard/setup.sh [--real-rail]
#
# It checks what the demo needs and installs what is missing, installs the pinned tools, and stops once for the one
# step only a person can do: choosing the demo Goose's model and signing in. Run it again at any time: it skips
# everything already done, so on a set-up Mac it changes nothing.
#
# The whole script is functions, and main runs on the last line: bash reads all of it before running any, so moving
# the checkout this file lives in (step 2) cannot change the code that is running, and a download cut short runs
# nothing.

# The pins. The RUNBOOK's header line is the one place for them: demo/ard/tests/test_pins.py checks that these agree
# with it, so a pin changes there and here in the same commit.
# capsulectl and its book and deal plugins come from the capsulectl release: capsule-cli's release and evidencebook's
# capsulectl/ release of the same version, each built from the commit below (each binary's --version names it).
# The evidencebook checkout is at the same commit, since the demo's code reads it (ARD_EVIDENCEBOOK).
CAPSULECTL_VERSION=v0.1.1
EVIDENCEBOOK_PIN=2ca6e8aafe5d36f12c036e8834b00eee776d9a12
CAPSULE_CLI_PIN=129a80f3ae9a88530cb85f3438f2f57a1deaf64c
CAPSULE_ENGINE_PIN=0263ff119911d91eb54dd3d3debdcc71324042eb
GOOSE_VERSION=1.59.2
ACP_VERSION=0.108.0

ORG=https://github.com/action-state-group
DEMO="$HOME/ard-demo"
SKILLS="$DEMO/evidencebook-skills"
VPY="$SKILLS/.venv/bin/python"
LOCAL_BIN="$HOME/.local/bin"
PLUGINS="$HOME/.local/lib/capsulectl/plugins"
APP=/Applications/Goose.app
CORE_V=$CAPSULECTL_VERSION
PLATFORM=darwin-arm64
REAL_RAIL=0
CONTINUED=0
LOG=""
DOING=""
PROVIDER=""
EXTENSIONS_TURNED_OFF=0

say() { printf '%s\n' "$*"; }
# A step that is already done says so once; after the hand-over to the checkout's copy (step 2) the checks of "What
# you need" run again quietly.
already() { [ "$CONTINUED" = 1 ] && [ "${QUIET_STEP:-0}" = 1 ] || printf '  %s\n' "$*"; }
stop() {
  printf '\nSet-up stopped: %s\n' "$*" >&2
  exit 1
}
# Run one command of the current step with its output in the log. On a failure: which step, and where the details are.
run() {
  if ! "$@" >>"$LOG" 2>&1; then
    KEEP_LOG=1
    printf '\nSet-up stopped while %s.\nThe details are in %s; send that file to whoever helps you.\n' "$DOING" "$LOG" >&2
    printf 'Once it is fixed, run this again: it skips everything already done.\n' >&2
    exit 1
  fi
}
ask() {  # ask <prompt>: one line from the person; stop if there is none (the input was closed)
  printf '%s' "$1"
  read -r REPLY || stop "no answer was typed. Run this again when you are at the keyboard."
}

# Install one missing formula or cask, without upgrading anything already installed (a dependency it shares, or the
# formulae that depend on it): Sherlock2 on #364, install only what is missing.
brew_install() {
  HOMEBREW_NO_INSTALL_UPGRADE=1 HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK=1 HOMEBREW_NO_AUTO_UPDATE=1 brew install "$@"
}

# ---- What you need -------------------------------------------------------------------------------------------------
need() {  # need <command> <brew formula> <what it is>
  if command -v "$1" >/dev/null 2>&1; then
    already "$3: already installed"
  else
    say "  Installing $3 with Homebrew (brew install $2) ..."
    DOING="installing $3"
    run brew_install "$2"
  fi
}

prerequisites() {
  QUIET_STEP=1
  [ "$CONTINUED" = 1 ] || say "Checking what the demo needs (it installs only what is missing and upgrades nothing you have) ..."
  [ "$(uname -s)" = Darwin ] || stop "this demo runs on a Mac."
  [ "$(uname -m)" = arm64 ] || stop "this Mac is not Apple silicon, and the demo uses the Apple silicon build of Goose."
  if ! command -v brew >/dev/null 2>&1 && [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  fi
  if command -v brew >/dev/null 2>&1; then
    already "Homebrew: already installed"
  else
    say "  Installing Homebrew, the Mac's package manager. Its installer asks for this Mac's password (it uses sudo)."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
      && [ -x /opt/homebrew/bin/brew ] || stop "Homebrew did not install. Install it from https://brew.sh, then run this again."
    eval "$(/opt/homebrew/bin/brew shellenv)"
  fi
  need git git git
  need jq jq jq
  need go go Go
  need node node Node.js
  need npm node npm
  need tmux tmux "tmux (the testbed's screens run in it)"
  [ "$REAL_RAIL" = 0 ] || need cargo rust "Rust (the real rail)"
  command -v lsof >/dev/null 2>&1 || stop "lsof is missing. macOS ships it in /usr/sbin, and the demo's reset needs it."
  PY=""
  local p
  for p in python3 "$(brew --prefix)/bin/python3"; do
    if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      PY=$(command -v "$p"); break
    fi
  done
  if [ -n "$PY" ]; then
    already "Python 3.10 or later: already installed"
  else
    say "  Installing Python 3 with Homebrew (brew install python) ..."
    DOING="installing Python 3"
    run brew_install python
    PY="$(brew --prefix)/bin/python3"
  fi
  QUIET_STEP=0
}

# ---- Step 2: the code ----------------------------------------------------------------------------------------------
at_commit() {  # at_commit <repository> <commit, or origin/<branch>>: clone it if missing; move it there unless it is
  local name=$1 want=$2 dir="$DEMO/$1" head target
  if [ ! -d "$dir/.git" ]; then
    [ ! -e "$dir" ] || stop "$dir is there but is not a git checkout. Move it aside, then run this again."
    say "  Downloading $name ..."
    DOING="downloading $name"
    run git clone -q "$ORG/$name" "$dir"
  fi
  head=$(git -C "$dir" rev-parse HEAD)
  if [ "$want" = "${want#origin/}" ]; then  # a commit: no network when it is there already
    target=$want
    # the demo is built from these checkouts, so one with changes of its own is never built from, at the pin or not
    [ -z "$(git -C "$dir" status --porcelain --untracked-files=no)" ] \
      || stop "$dir has changes of its own, and the demo is built only from ${target:0:7}, unchanged. Keep them elsewhere (git -C \"$dir\" stash), then run this again."
    if [ "$head" = "$target" ]; then already "$name: already at ${target:0:7}"; return 0; fi
    DOING="getting $name ${target:0:7}"
    run git -C "$dir" fetch -q origin "$target"
  else  # a branch: fetch it to see where it is now
    DOING="getting $name"
    run git -C "$dir" fetch -q origin
    target=$(git -C "$dir" rev-parse "$want")
    if [ "$head" = "$target" ]; then already "$name: already at ${target:0:7}"; return 0; fi
  fi
  [ -z "$(git -C "$dir" status --porcelain --untracked-files=no)" ] \
    || stop "$dir has changes of its own, so it was not moved. Keep them elsewhere (git -C \"$dir\" stash), then run this again."
  say "  Setting $name to ${target:0:7} ..."
  DOING="moving $name to ${target:0:7}"
  run git -C "$dir" checkout -q --detach "$target"
}

# ---- Step 3: capsulectl with the book and deal plugins -------------------------------------------------------------
capsulectl_at_pin() {
  local l
  "$LOCAL_BIN/capsulectl" --version 2>/dev/null | grep -qF "capsulectl $CORE_V (commit $CAPSULE_CLI_PIN" || return 1
  for l in book deal; do  # each plugin names the evidencebook commit it was built from
    "$PLUGINS/capsulectl-$l" --version 2>/dev/null | grep -qF "capsulectl-$l $CORE_V (commit $EVIDENCEBOOK_PIN" || return 1
  done
  "$LOCAL_BIN/capsulectl" plugin ls 2>/dev/null | jq -e '.refused == []' >/dev/null 2>&1 || return 1
  [ -d "$PLUGINS/standard-history-module" ] && [ -d "$PLUGINS/capsulectl-deal.d" ]
}
# fetch_release <url> <folder> <file>...: each file and the release's SHA256SUMS into the folder, each file checked
# against its own SHA256SUMS line (a file the list does not name fails)
fetch_release() {
  local url=$1 dir=$2 f line
  shift 2
  rm -rf "$dir" && mkdir -p "$dir" && curl -fsSL -o "$dir/SHA256SUMS" "$url/SHA256SUMS" || return 1
  for f in "$@"; do
    curl -fsSL -o "$dir/$f" "$url/$f" || return 1
    line=$(awk -v f="$f" '$2 == f && $1 ~ /^[0-9a-f]+$/ && length($1) == 64' "$dir/SHA256SUMS")
    [ -n "$line" ] || { echo "$f is not in $url/SHA256SUMS"; return 1; }
    (cd "$dir" && printf '%s\n' "$line" | shasum -a 256 -c -) || return 1
  done
}
download_release() {  # capsulectl from capsule-cli's release, its plugins and their views from evidencebook's
  fetch_release "$ORG/capsule-cli/releases/download/$CORE_V" "$DEMO/dist/$CORE_V/capsule-cli" \
    "capsulectl-$CORE_V-$PLATFORM" \
    && fetch_release "$ORG/evidencebook/releases/download/capsulectl/$CORE_V" "$DEMO/dist/$CORE_V/evidencebook" \
      "capsulectl-book-$CORE_V-$PLATFORM" "capsulectl-deal-$CORE_V-$PLATFORM" \
      "standard-history-$CORE_V.tar.gz" "deal-view-$CORE_V.tar.gz"
}
install_release() {  # the views first, the plugins last: a plugin at the pin then means its views are from the same release
  local d="$DEMO/dist/$CORE_V"
  install -m 0755 "$d/capsule-cli/capsulectl-$CORE_V-$PLATFORM" "$LOCAL_BIN/capsulectl" \
    && tar -xzf "$d/evidencebook/standard-history-$CORE_V.tar.gz" -C "$PLUGINS" \
    && tar -xzf "$d/evidencebook/deal-view-$CORE_V.tar.gz" -C "$PLUGINS" \
    && "$LOCAL_BIN/capsulectl" plugin install "$d/evidencebook/capsulectl-book-$CORE_V-$PLATFORM" \
    && "$LOCAL_BIN/capsulectl" plugin install "$d/evidencebook/capsulectl-deal-$CORE_V-$PLATFORM"
}
capsulectl_step() {
  say "capsulectl and its book and deal plugins ..."
  if capsulectl_at_pin; then already "already installed ($CORE_V)"; return 0; fi
  say "  Downloading the $CORE_V release ..."
  mkdir -p "$LOCAL_BIN" "$PLUGINS"
  DOING="downloading the capsulectl $CORE_V release"; run download_release
  DOING="installing capsulectl and its book and deal plugins"; run install_release
  DOING="checking capsulectl and its plugins"; run capsulectl_at_pin
  say "  Installed $CORE_V."
}

# ---- Step 4: capsule-engine and the Python environment -------------------------------------------------------------
engine_at_pin() {
  local info
  info=$(go version -m "$DEMO/bin/capsule-engine" 2>/dev/null) || return 1
  printf '%s\n' "$info" | grep -qF "vcs.revision=$CAPSULE_ENGINE_PIN" && printf '%s\n' "$info" | grep -qF "vcs.modified=false"
}
build_engine() {
  mkdir -p "$DEMO/bin" && (cd "$DEMO/capsule-engine/go" && go build -o "$DEMO/bin/capsule-engine" ./cmd/capsule-engine)
}
venv_ready() {
  [ -x "$VPY" ] && "$VPY" - >/dev/null 2>&1 <<'PY'
import sys
from importlib.metadata import version
for p in ("cryptography", "pyyaml", "rfc8785"):
    version(p)
sys.exit(version("mcp") != "2.3.0")
PY
}
engine_and_venv_step() {
  say "capsule-engine ..."
  if engine_at_pin; then already "already built (${CAPSULE_ENGINE_PIN:0:7})"
  else
    say "  Building it ..."
    DOING="building capsule-engine"; run build_engine
    DOING="checking capsule-engine"; run engine_at_pin
  fi
  say "The demo's Python environment ..."
  if venv_ready; then already "already made"; return 0; fi
  say "  Making it ..."
  DOING="making the Python environment"
  # a venv cut short (python there, pip not) is made again
  "$VPY" -m pip --version >/dev/null 2>&1 || run "$PY" -m venv --clear "$SKILLS/.venv"
  run "$VPY" -m pip install -q cryptography pyyaml rfc8785 "mcp==2.3.0"
  run venv_ready
}

# ---- Step 5: Goose Desktop -----------------------------------------------------------------------------------------
goose_running() { pgrep -f "Goose.app/Contents/MacOS/Goose" >/dev/null 2>&1; }
quit_goose() {
  goose_running || return 0
  say "  Quitting Goose ..."
  osascript -e 'quit app "Goose"' >/dev/null 2>&1 || true
  local _
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do goose_running || return 0; sleep 1; done
  stop "Goose did not quit. Quit it yourself (Goose menu, Quit Goose), then run this again."
}
install_goose() {
  local dl
  dl=$(mktemp -d "${TMPDIR:-/tmp}/ard-goose.XXXXXX") || return 1
  curl -fsSL -o "$dl/Goose.zip" "https://github.com/aaif-goose/goose/releases/download/v$GOOSE_VERSION/Goose-darwin-arm64.zip" \
    && ditto -x -k "$dl/Goose.zip" "$dl/x" && [ -d "$dl/x/Goose.app" ] \
    && rm -rf "$APP" && mv "$dl/x/Goose.app" /Applications/ && rm -rf "$dl"
}
goose_step() {
  say "Goose Desktop $GOOSE_VERSION ..."
  if [ "$(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist" 2>/dev/null)" = "$GOOSE_VERSION" ]; then
    already "already installed"; return 0
  fi
  if [ -d "$APP" ]; then say "  Replacing the Goose in Applications with $GOOSE_VERSION ..."
  else say "  Installing it into Applications ..."; fi
  quit_goose
  DOING="downloading and installing Goose Desktop $GOOSE_VERSION"
  run install_goose
}

# ---- Steps 6 to 9: the demo's own Goose, its model and its extensions ----------------------------------------------
# Reads the demo Goose's settings with open-windows.py's own code, so this script checks exactly what open-windows.py
# checks before it opens the windows. Prints one JSON object; "off" also turns every extension off (step 9).
goose_status() {  # goose_status [off]
  "$VPY" - "$SKILLS/demo/ard/goose/open-windows.py" "${1:-}" <<'PY'
import importlib.util, json, os, sys, tempfile
spec = importlib.util.spec_from_file_location("ow", sys.argv[1])
ow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ow)
root = ow.goose_root()
out = {"root": str(root), "changed": False}
try:
    if sys.argv[2] == "off":
        # every extension on in the settings Goose runs on (the system file's too), switched off in the demo
        # Goose's own file, which Goose reads last; the file is replaced whole, so a stop midway leaves the old one
        import yaml
        on = [k for k, v in ow.goose_config(root)["extensions"].items()
              if isinstance(v, dict) and v.get("enabled") and k not in ow.KEPT_ON]
        if on:
            f = root / "config" / "config.yaml"
            doc = ow._yaml(f)
            ext = doc.setdefault("extensions", {}) or {}
            doc["extensions"] = ext
            for k in on:
                ext[k] = {**(ext.get(k) or {}), "enabled": False}
            tmp = None
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".config.yaml.")
                with os.fdopen(fd, "w") as fh:
                    fh.write(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
                os.replace(tmp, f)
            except OSError as exc:
                if tmp and os.path.exists(tmp):
                    os.unlink(tmp)
                raise ow.ConfigError(f"{f} could not be written ({exc.strerror or exc})") from exc
            out["changed"] = True
    cfg = ow.goose_config(root)
    out["on"] = sorted(str(v.get("display_name") or k) for k, v in cfg["extensions"].items()
                       if isinstance(v, dict) and v.get("enabled") and k not in ow.KEPT_ON)
except ow.ConfigError as exc:
    out["error"] = str(exc)
problem, provider = ow.check_provider(root)
out["problem"], out["provider"] = problem, provider
# the person's step is needed when no provider is chosen yet or the one chosen runs its own agent; any other problem
# is the script's to fix (the adapter, the extensions) or a message to show
extra = ow.launchd_env("GOOSE_ADDITIONAL_CONFIG_FILES")
chosen = ow.launchd_env("GOOSE_PROVIDER") or ow.provider_of(cfg) if "error" not in out else None
out["needs_choice"] = not extra and "error" not in out and (not chosen or chosen in ow.AGENT_PROVIDERS)
out["provider"] = provider or chosen
print(json.dumps(out))
PY
}
field() { printf '%s' "$1" | jq -r "$2"; }

install_acp() {  # step 6: the demo's own Claude Code adapter, pinned, under ~/ard-demo (never npm install -g)
  local pkg="$DEMO/acp/node_modules/@agentclientprotocol/claude-agent-acp/package.json"
  if [ "$(jq -r .version "$pkg" 2>/dev/null)" = "$ACP_VERSION" ] && [ -x "$DEMO/acp/node_modules/.bin/claude-agent-acp" ]; then
    already "the demo's Claude Code adapter: already installed ($ACP_VERSION)"
  else
    say "  Installing the demo's own Claude Code adapter $ACP_VERSION into $DEMO/acp (only the demo uses it) ..."
    DOING="installing the Claude Code adapter"
    run npm install --prefix "$DEMO/acp" "@agentclientprotocol/claude-agent-acp@$ACP_VERSION"
  fi
}
claude_signed_in() { claude auth status 2>/dev/null | jq -e '.loggedIn == true' >/dev/null 2>&1; }
claude_code() {  # the claude CLI and its sign-in, for Claude Code ACP
  if command -v claude >/dev/null 2>&1; then already "Claude Code: already installed"
  else
    say "  Installing Claude Code with Homebrew (brew install --cask claude-code) ..."
    DOING="installing Claude Code"
    run brew_install --cask claude-code
  fi
  if claude_signed_in; then already "Claude Code: already signed in"; return 0; fi
  say "  Sign in to Claude Code: a browser page opens; sign in there with your Claude account, then come back here."
  claude auth login || stop "the Claude Code sign-in did not finish. Run this again to try once more."
  claude_signed_in || stop "Claude Code is still not signed in. Run this again to try once more."
}

start_demo_goose() {
  DOING="starting the demo's own Goose"
  run "$VPY" "$SKILLS/demo/ard/goose/open-windows.py" --goose-only
}

# Set-up step 8, the person's one step: choose the model, sign in, check that it answers.
choose_model() {
  local choice status
  say ""
  say "One step is yours: choose the model the demo's Goose windows use."
  say "  1  Claude Code (your Claude subscription)"
  say "  2  Another provider: ChatGPT Codex (a ChatGPT sign-in) or an API key (Google, OpenAI, Anthropic and others)"
  while :; do
    ask "Type 1 or 2, then press Return: "
    choice=$REPLY
    case "$choice" in 1|2) break ;; esac
  done
  if [ "$choice" = 1 ]; then install_acp; claude_code; QUIET_STEP=1; fi
  quit_goose
  say "  Starting the demo's own Goose ..."
  start_demo_goose
  say ""
  say "In the Goose window that just opened (maximize it if it is small):"
  say "  1. Click Connect to a Provider."
  if [ "$choice" = 1 ]; then
    say "  2. Type claude in the search box, pick Claude Code ACP, wait for \"ACP adapter found\", then click Continue."
  else
    say "  2. Pick your provider and follow its screens: ChatGPT Codex, then sign in; or Google, OpenAI or Anthropic,"
    say "     then paste your API key. Only the demo's Goose keeps it."
  fi
  say "  3. On the privacy screen, untick \"Share anonymous usage data\" if you like, then click Get Started."
  say "  4. Type hello in the chat and check that it answers."
  while :; do
    ask "When it has answered, press Return here: "
    quit_goose
    status=$(goose_status off) || stop "the demo Goose's settings could not be read."
    [ "$(field "$status" '.error // ""')" = "" ] || stop "$(field "$status" .error)"
    [ "$(field "$status" .changed)" = false ] || EXTENSIONS_TURNED_OFF=1
    if [ "$(field "$status" .needs_choice)" = false ]; then break; fi
    say ""
    # with no model chosen yet, open-windows.py's message points at a command; this step is where the person is
    if [ "$(field "$status" '.provider // ""')" = "" ]; then say "  Not yet: no model is chosen in the demo's Goose."
    else say "  Not yet: $(field "$status" .problem)."; fi
    say "  Starting the demo's Goose again: choose the model as above."
    start_demo_goose
  done
}

goose_settings_step() {
  local status provider
  status=$(goose_status) || stop "the demo Goose's settings could not be read."
  say "The demo's own Goose (its settings: $(field "$status" .root); your own Goose is never changed) ..."
  [ "$(field "$status" '.error // ""')" = "" ] || stop "$(field "$status" .error)"
  if [ "$(field "$status" .needs_choice)" = true ]; then
    choose_model
  else
    already "model: already chosen ($(field "$status" .provider))"
  fi
  status=$(goose_status) || stop "the demo Goose's settings could not be read."
  provider=$(field "$status" '.provider // ""')
  if [ "$provider" = claude-acp ]; then install_acp; claude_code; fi
  QUIET_STEP=0
  # step 9: every extension off, so each window's agent has only its own demo tools and cannot click the payment dialog
  if [ "$(field "$status" '.on | length')" != 0 ]; then
    quit_goose
    status=$(goose_status off) || stop "the demo Goose's settings could not be read."
    [ "$(field "$status" '.error // ""')" = "" ] || stop "$(field "$status" .error)"
    EXTENSIONS_TURNED_OFF=1
  fi
  if [ "$EXTENSIONS_TURNED_OFF" = 1 ]; then say "  Turned off every Goose extension in the demo's Goose."
  else already "Goose extensions: already all off"; fi
  [ "$(field "$status" '.on | length')" = 0 ] \
    || stop "these Goose extensions are still on: $(field "$status" '.on | join(", ")'). One switched on in /etc/goose/config.yaml cannot be switched off here; ask whoever looks after this Mac."
  status=$(goose_status) || stop "the demo Goose's settings could not be read."
  [ "$(field "$status" '.problem // ""')" = "" ] || stop "$(field "$status" .problem)"
  PROVIDER=$(field "$status" .provider)
  case "$PROVIDER" in  # Sherlock2 on #365: the summary names the provider, by the name its screen shows
    claude-acp) PROVIDER="Claude Code (adapter $ACP_VERSION)" ;;
    chatgpt_codex) PROVIDER="ChatGPT Codex" ;;
    google) PROVIDER=Google ;;
    openai) PROVIDER=OpenAI ;;
    anthropic) PROVIDER=Anthropic ;;
  esac
}

# Last: a real stamp on a throwaway log, so a witness whose home page answers but that takes no stamps stops the set-up
# here and not in the middle of a run (evidencebook-skills#359; demo/ard/witness_check.py).
witness_step() {
  # testbed.sh hands this check to the testbed, which measures the hosted witness and offers the local one when it is
  # slow (evidencebook-skills#382): a slow or refusing hosted witness must not stop the set-up before that offer
  if [ "${ARD_SETUP_WITNESS:-}" = testbed ]; then
    say "Action State's witness: the testbed measures it next."
    return 0
  fi
  say "Action State's witness: one test stamp (it can take up to a minute) ..."
  local out
  if out=$(ARD_EVIDENCEBOOK="$DEMO/evidencebook" CAPSULECTL_DEAL="$PLUGINS/capsulectl-deal" \
           "$VPY" "$SKILLS/demo/ard/witness_check.py" 2>&1); then
    say "  $out"
  else
    stop "$out"
  fi
}

main() {
  set -euo pipefail
  local arg
  for arg in ${1+"$@"}; do
    case "$arg" in
      --real-rail) REAL_RAIL=1 ;;
      --continue) CONTINUED=1 ;;  # set by this script when it hands over to the checkout's copy (step 2)
      -h|--help) say "Sets up the ARD demo on this Mac (RUNBOOK.md, \"Set up, once\"). Run it again at any time: it skips what is done."
                 say "  --real-rail  also check for Rust, which the real rail needs"; return 0 ;;
      *) stop "unknown option $arg (the only option is --real-rail)." ;;
    esac
  done
  LOG=$(mktemp "${TMPDIR:-/tmp}/ard-setup.XXXXXX")
  KEEP_LOG=0
  trap '[ "$KEEP_LOG" = 1 ] || rm -f "$LOG"' EXIT
  prerequisites
  if [ "$CONTINUED" = 0 ]; then
    say "Getting the code into $DEMO ..."
    mkdir -p "$DEMO"
    # evidencebook-skills runs at main; ARD_SKILLS_REF names another ref, only to try a branch before it merges
    at_commit evidencebook-skills "${ARD_SKILLS_REF:-origin/main}"
    # The checkout's own copy of this script does the rest, with the pins of the commit just checked out.
    rm -f "$LOG"
    exec /bin/bash "$SKILLS/demo/ard/setup.sh" --continue ${1+"$@"}
  fi
  at_commit evidencebook "$EVIDENCEBOOK_PIN"
  at_commit capsule-engine "$CAPSULE_ENGINE_PIN"
  export GOTOOLCHAIN=auto PATH="$LOCAL_BIN:$PATH"
  capsulectl_step
  engine_and_venv_step
  goose_step
  goose_settings_step
  witness_step
  say ""
  say "Set-up is done at evidencebook-skills $(git -C "$SKILLS" rev-parse --short=7 HEAD), capsulectl $CORE_V (capsule-cli ${CAPSULE_CLI_PIN:0:7}, evidencebook ${EVIDENCEBOOK_PIN:0:7}), capsule-engine ${CAPSULE_ENGINE_PIN:0:7}, Goose Desktop $GOOSE_VERSION, provider $PROVIDER."
  say "Next: \"Before each run\" in the RUNBOOK."
}

main ${1+"$@"}
exit
