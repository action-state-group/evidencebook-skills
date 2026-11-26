# Notes for contributors and agents

AGENTS.md cannot hold these: the repository root may carry no AGENTS.md (tests/test_skill_tree.py).

## Local check

Before every push: `scripts/check.sh` (about 13 minutes on an Apple-silicon Mac; needs git, gh signed in, Go, uv, python3, bash 4.4 or later and Google Chrome, and fetches its pinned checkouts and released binaries into `~/.cache/evidencebook-skills-check`). It runs every job of `fast.yml` and `tests.yml` with CI's commands, except that `ard-demo`, the one end-to-end job, runs only when a file it reads changed since the merge base with `origin/main` (the list is `ARD_INPUTS` in the script); it prints one line saying which and why. `scripts/check.sh --full` runs every job whatever changed. `scripts/check.sh --plan` prints the selection and runs nothing. No job binds a fixed port (ard-demo picks a free stage port, and its witness, local since #371, a free one too) and runs at the same time share the dependency cache under a lock, so the check needs no e2e lock: `asg-local-check --heavy scripts/check.sh`.

Pull requests run only the fast set (`fast.yml`); `ard-demo` and `tau2-live` run nightly and on main (`tests.yml`). To run them on a branch's CI, dispatch `heavy tests` on it: `gh workflow run tests.yml --ref BRANCH`.
