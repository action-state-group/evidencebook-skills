# Notes for contributors and agents

AGENTS.md cannot hold these: the repository root may carry no AGENTS.md (tests/test_skill_tree.py).

## Local check

Before every push: `scripts/check.sh` (about 13 minutes on an Apple-silicon Mac; needs git, gh signed in, Go, uv, python3, bash 4.4 or later and Google Chrome, and fetches its pinned checkouts and released binaries into `~/.cache/evidencebook-skills-check`). It runs every job of `fast.yml` and `tests.yml` with CI's commands. `scripts/check.sh --full` is the same set, since main and nightly run nothing more, so no change needs more than `scripts/check.sh`.

Pull requests run only the fast set (`fast.yml`); `ard-demo` and `tau2-live` run nightly and on main (`tests.yml`). To run them on a branch's CI, dispatch `heavy tests` on it: `gh workflow run tests.yml --ref BRANCH`.
