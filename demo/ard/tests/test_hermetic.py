# SPDX-License-Identifier: Apache-2.0
"""The tests never use the person's own demo folders (evidencebook-skills#357, #324): each demo folder is a fresh one,
and a test that reaches a real one fails, whether that folder exists (a laptop with a seeded home) or not (CI)."""
import os
from pathlib import Path

import pytest

import conftest


def test_each_demo_folder_is_a_fresh_one_outside_the_persons_own():
    real = [os.path.realpath(r) for r in conftest.REAL_FOLDERS]
    for var in conftest.DEMO_HOMES:
        value = os.environ[var]
        assert Path(value).is_dir(), var
        assert not conftest._inside(os.path.realpath(value), real), var


@pytest.mark.parametrize("folder", conftest.REAL_FOLDERS, ids=lambda p: p.name)
def test_a_read_of_a_real_demo_folder_fails_the_test(folder):
    # A name that exists nowhere: the guard refuses before the file system is asked, so this changes nothing.
    with pytest.raises(conftest.RealFolderTouched):
        open(folder / "pages" / "never-there-0b1e")
    with pytest.raises(conftest.RealFolderTouched):
        os.listdir(folder)
    assert conftest.GUARD.take(), "the refusal is noted too"  # taken here, or this test would fail for it


def test_a_refusal_the_code_swallows_still_fails_the_test():
    try:
        Path(conftest.REAL_FOLDERS[0], "stage", "x.json").read_text()
    except Exception:  # code under test that hides errors
        pass
    touched = conftest.GUARD.take()
    assert touched and touched[0].startswith("open ") and touched[0].endswith("x.json")


@pytest.mark.parametrize("present", [True, False], ids=["seeded", "absent"])
def test_the_guard_acts_the_same_whether_the_folder_exists(tmp_path, present):
    root = tmp_path / "ard-commerce-demo"
    if present:
        (root / "pages").mkdir(parents=True)
        (root / "pages" / "maya.html").write_text("seeded")
    guard = conftest._Guard([root])
    for event, args in (("open", (str(root / "pages" / "maya.html"), "r", 0)), ("os.listdir", (root,)),
                        ("os.mkdir", (root / "pages", 0o777, None)), ("os.rename", (tmp_path / "a", root / "b", None, None))):
        with pytest.raises(conftest.RealFolderTouched):
            guard(event, args)
    guard("open", (str(tmp_path / "ard-commerce-demo-other"), "r", 0))  # a sibling with the same prefix is not inside
    guard("open", (3, "r", 0))  # an open file descriptor names no path
    guard("os.stat", (root,))
    assert len(guard.take()) == 4


def test_a_variable_that_names_a_real_folder_is_refused(tmp_path):
    env = {var: str(tmp_path / var) for var in conftest.DEMO_HOMES}
    assert conftest.demo_homes(env) == env
    env["ARD_HOME"] = str(conftest.REAL_FOLDERS[0])
    with pytest.raises(pytest.UsageError, match="ARD_HOME=.* is the person's own demo folder"):
        conftest.demo_homes(env)
    env["ARD_HOME"] = str(conftest.REAL_FOLDERS[2] / "deals")  # inside ~/ard-demo/testbed
    with pytest.raises(pytest.UsageError):
        conftest.demo_homes(env)


def test_a_refusal_makes_no_folder_first():
    made = []
    with pytest.raises(pytest.UsageError, match="ARD_GOOSE_ROOT"):
        conftest.demo_homes({"ARD_GOOSE_ROOT": str(conftest.REAL_FOLDERS[1])}, make=made.append)
    assert made == []


def test_the_checkouts_beside_the_testbed_stay_readable():
    # The RUNBOOK keeps this repository's and evidencebook's checkouts in ~/ard-demo: tests run from there.
    ard_demo = conftest.REAL_FOLDERS[2].parent
    for p in (ard_demo / "evidencebook-skills" / "demo" / "ard" / "pages.py", ard_demo / "evidencebook" / "go.mod"):
        conftest.GUARD("open", (str(p), "r", 0))
    assert conftest.GUARD.take() == []


def test_a_root_that_is_a_symbolic_link_is_guarded_under_both_names(tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "ard-commerce-demo"
    link.symlink_to(target)
    guard = conftest._Guard([link])
    for p in (link / "pages" / "a.html", target / "pages" / "a.html"):
        with pytest.raises(conftest.RealFolderTouched):
            guard("open", (str(p), "r", 0))


def test_an_unset_variable_gets_a_folder_of_its_own(tmp_path):
    made = conftest.demo_homes({}, make=lambda var: str(tmp_path / var))
    assert made == {var: str(tmp_path / var) for var in conftest.DEMO_HOMES}
