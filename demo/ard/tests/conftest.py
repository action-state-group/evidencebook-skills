# SPDX-License-Identifier: Apache-2.0
import atexit
import os
import pwd
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import _paths  # noqa: E402

_paths.setup()

# The tests never use the person's own demo folders (evidencebook-skills#357, #324): a laptop holds a seeded demo home
# that CI's clean runner lacks, so a test that read it passed locally and failed on main (#353). Each folder below is
# taken from its variable when that is set (scripts/check.sh gives every job fresh, empty ones) and is otherwise a fresh,
# empty one of this test process's own, so a laptop and CI test the same thing. The real folders are those of the user
# this process runs as, from the password database: a test that changes $HOME (test_reset.py's ``mac``) never moves them.
DEMO_HOMES = ("ARD_HOME", "ARD_GOOSE_ROOT", "ARD_TESTBED", "ARD_ACP_PREFIX", "ARD_CAPSULE_ANCHOR")
_USER = Path(pwd.getpwuid(os.getuid()).pw_dir)
#: The person's own folders the demo's code reaches by default: the demo home (demo.DEFAULT_HOME), its Goose root
#: (reset.GOOSE_ROOT_DEFAULT), ~/ard-demo (the testbed, its capsule-anchor checkout and the ACP prefix), and the
#: person's own Goose settings and recipe trust, which reset.clear_recipe_trust edits.
REAL_FOLDERS = [_USER / ".config" / "ard-commerce-demo", _USER / ".config" / "ard-commerce-goose", _USER / "ard-demo",
                _USER / ".config" / "goose", _USER / "Library" / "Application Support" / "Goose"]


def _inside(path: str, roots) -> bool:
    return any(path == str(r) or path.startswith(str(r) + os.sep) for r in roots)


def demo_homes(env, make=lambda var: tempfile.mkdtemp(prefix=f"{var.lower()}-")) -> dict[str, str]:
    """The folder each of :data:`DEMO_HOMES` takes: ``env``'s value, else ``make(var)``. A value inside one of
    :data:`REAL_FOLDERS` is refused."""
    out = {}
    for var in DEMO_HOMES:
        value = env.get(var) or make(var)
        if _inside(os.path.realpath(os.path.expanduser(value)), [os.path.realpath(r) for r in REAL_FOLDERS]):
            raise pytest.UsageError(f"{var}={value} is the person's own demo folder; the tests use a fresh one "
                                    f"(unset {var}, or point it at an empty folder)")
        out[var] = value
    return out


_made = [v for v in DEMO_HOMES if not os.environ.get(v)]
os.environ.update(demo_homes(os.environ))
for _var in _made:
    atexit.register(shutil.rmtree, os.environ[_var], True)


class RealFolderTouched(RuntimeError):
    """A test reached one of :data:`REAL_FOLDERS`."""


class _Guard:
    """An audit hook that refuses any file operation under :data:`REAL_FOLDERS` (``os.stat`` raises no audit event, so
    a bare existence check passes). The refusal is raised where the operation is, and also noted, because code that
    catches the error (``except Exception``, say) would hide it: the test that made it fails afterwards all the same."""

    #: The events whose first one or two arguments are paths.
    EVENTS = {"open": 1, "os.listdir": 1, "os.scandir": 1, "os.mkdir": 1, "os.remove": 1, "os.rmdir": 1, "os.chmod": 1,
              "os.truncate": 1, "os.utime": 1, "shutil.rmtree": 1, "os.rename": 2, "os.replace": 2, "os.link": 2,
              "os.symlink": 2, "shutil.copytree": 2, "shutil.copyfile": 2, "shutil.move": 2}

    def __init__(self, roots):
        self.roots = [os.path.abspath(r) for r in roots]
        self.touched: list[str] = []

    def __call__(self, event, args):
        n = self.EVENTS.get(event)
        if not n:
            return
        for arg in args[:n]:
            if isinstance(arg, (str, bytes, os.PathLike)):
                p = os.fsdecode(os.fspath(arg))
                p = os.path.normpath(p if os.path.isabs(p) else os.path.join(os.getcwd(), p))
                if _inside(p, self.roots):
                    self.touched.append(f"{event} {p}")
                    raise RealFolderTouched(f"{event} {p}: the tests never use the person's own demo folders "
                                            "(conftest.REAL_FOLDERS); use the fresh one in the folder's variable")

    def take(self) -> list[str]:
        out, self.touched = self.touched, []
        return out


GUARD = _Guard(REAL_FOLDERS)
sys.addaudithook(GUARD)


def _fail_if_touched(when: str) -> None:
    touched = GUARD.take()
    if touched:
        pytest.fail(f"touched the person's own demo folders ({when}): " + "; ".join(touched), pytrace=False)


@pytest.fixture(autouse=True)
def _no_real_folder():
    _fail_if_touched("in a fixture set up for this test")  # a module or session fixture may have
    yield
    _fail_if_touched("in this test")


def pytest_sessionfinish(session):
    # What a fixture's teardown touched after the last test.
    touched = GUARD.take()
    if touched:
        print("\ntouched the person's own demo folders: " + "; ".join(touched), file=sys.stderr)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


os.environ.setdefault("CAPSULE_WITNESS", "off")
# Every agreement names Action State's hosted witness by default (party.WITNESS_URL); the unit tests never reach it, and
# only tests/test_e2e.py turns it back on.
os.environ.setdefault("ARD_WITNESS", "off")
# pytest-xdist workers compile the pack at the same time: each compiles into a folder of its own (pack.compile_source),
# and the servers a test starts inherit it.
if os.environ.get("PYTEST_XDIST_WORKER"):
    os.environ["ARD_PACK_WORK"] = os.environ["PYTEST_XDIST_WORKER"]


def needs_engine() -> bool:
    return bool(os.environ.get("CAPSULE_ENGINE"))


engine_only = pytest.mark.skipif(not needs_engine(), reason="CAPSULE_ENGINE names the evaluator")

_SEEDED: dict[str, Path] = {}


@pytest.fixture(scope="session")
def seeded_home(tmp_path_factory):
    """``seeded_home(dest, kestrel_card)`` fills ``dest`` with a copy of a seeded demo home. Seeding the sample
    history takes about 35 s on CI, so each test process seeds once per ``kestrel_card`` mode and every module gets
    its own copy (nodes open their books by paths under the home, so a copy is a home of its own)."""
    import fcntl
    import shutil

    # Under pytest-xdist the workers share the parent of their base temp, so they seed each mode once between them.
    root = tmp_path_factory.getbasetemp()
    if os.environ.get("PYTEST_XDIST_WORKER"):
        root = root.parent

    def make(dest: Path, kestrel_card: str = "sentinel") -> Path:
        if kestrel_card not in _SEEDED:
            home, done = root / f"seeded-{kestrel_card}", root / f"seeded-{kestrel_card}.done"
            with open(root / f"seeded-{kestrel_card}.lock", "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)  # one process seeds; the others wait, then copy
                if not done.exists():
                    import seed
                    from world import World

                    shutil.rmtree(home, ignore_errors=True)  # a seed cut off part way is not reused
                    with World(home) as world:
                        seed.seed(world, say=lambda *_: None, kestrel_card=kestrel_card)
                    done.touch()
            _SEEDED[kestrel_card] = home
        shutil.copytree(_SEEDED[kestrel_card], dest, dirs_exist_ok=True)
        return dest

    return make
