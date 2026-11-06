"""The Terms Pack Studio workspace state (evidencebook-skills#130): what a pack folder
under <workspace>/packs/<pack_id>/ remembers so a different agent, or a shell, can pick up
partway. Two files, both plain JSON/JSONL, written only by `terms` verbs:

    workspace.json   the dataset reference (kind, path, digest of the sales read) and the last run
    history.jsonl    one line per pack digest: the digest, version, first/last time, the latest
                     run that used it, whether it was published
    history/<digest12>.yaml   the pack source at that digest, which `terms checkout` restores

Undo is `terms checkout SRC DIGEST`, then `terms run SRC` over the same dataset, then
`terms compare` of the two digests. No authoring transcript is kept here; `keep_transcript`
is the opt-in, private copy (Terms Pack Studio PRD §12 Q9).
"""
import datetime
import hashlib
import json
import os
import pathlib
import shutil

import rfc8785


class WorkspaceError(ValueError):
    """A refusal, said in words (terms.main prints it like a TermsError)."""


def _checked(path):
    if path.is_symlink():
        raise WorkspaceError(f"{path} is a link; refusing to write through it")
    return path


def subdir(folder, name, mode=None):
    """folder/name as a real directory (a link is refused: it would carry writes out of the workspace)."""
    d = folder / name
    if d.is_symlink() or (d.exists() and not d.is_dir()):
        raise WorkspaceError(f"{d} is a link or not a folder; refusing to write through it")
    if not d.exists():
        d.mkdir(mode=mode) if mode else d.mkdir()
    return d


def _write(path, text):
    _checked(path)
    tmp = path.with_name(path.name + ".tmp")
    _checked(tmp)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        raise WorkspaceError(f"{path} is not readable JSON: {e}")


def sales_digest(sales):
    return hashlib.sha256(rfc8785.dumps(sorted(hashlib.sha256(rfc8785.dumps(s)).hexdigest() for s in sales))).hexdigest()


def dataset_ref(args, sales, ws):
    """The reference `terms init`/`run` was given: kind, path (relative to the workspace when it sits
    inside it, so the folder can move; absolute otherwise), how many sales, their digest."""
    for kind in ("deals", "exports", "store"):
        value = getattr(args, kind, None)
        if value:
            path = pathlib.Path(value).expanduser().resolve()
            if ws == path or ws in path.parents:
                path = path.relative_to(ws)
            return {"kind": kind, "path": str(path),
                    "sales": len(sales), "sales_digest": sales_digest(sales)}
    return None


def state(folder):
    return read_json(folder / "workspace.json", {})


def save_state(folder, st):
    _write(folder / "workspace.json", json.dumps(st, indent=2) + "\n")


def history(folder):
    path = folder / "history.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(l) for l in lines if l.strip()]
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise WorkspaceError(f"{path} is not readable: {e}")


def record(folder, source_path, digest, version, at, run=None, rehearsal=None, published=None):
    """Add or update the one line for `digest` and snapshot the source it was made from."""
    entries = history(folder)
    entry = next((e for e in entries if e["digest"] == digest), None)
    if entry is None:
        entry = {"digest": digest, "version": version, "first_at": at, "run": None, "rehearsal": None, "published": None}
        entries.append(entry)
    entry["last_at"] = at
    if run is not None:
        entry["run"], entry["rehearsal"] = run, bool(rehearsal)
    if published is not None:
        entry["published"] = published
    # The snapshot is the source as last run or published under this digest: the digest leaves out
    # words such as the title, so the latest bytes win and `checkout` can tell an unrecorded edit.
    snap = subdir(folder, "history") / f"{digest[:12]}.yaml"
    _checked(snap)
    shutil.copyfile(source_path, snap)
    _write(folder / "history.jsonl", "".join(json.dumps(e) + "\n" for e in entries))
    return entry


def find(entries, prefix, where):
    hits = [e for e in entries if e["digest"].startswith(prefix)] if prefix else []
    if len(prefix) < 6 or not hits:
        raise WorkspaceError(f"no pack digest starting {prefix!r} in {where} (at least 6 characters; `terms history` lists them)")
    if len(hits) > 1:
        raise WorkspaceError(f"{prefix!r} matches {len(hits)} digests in {where}; give more of it")
    return hits[0]


def run_of_digest(ws, prefix):
    """The result.json of the latest run under the pack digest starting `prefix`, found through
    every pack's history in the workspace."""
    packs = ws / "packs"
    hits = []
    for folder in sorted(packs.iterdir()) if packs.is_dir() else []:
        if not folder.is_dir():
            continue
        try:
            hits += [(folder, e) for e in history(folder) if prefix and e["digest"].startswith(prefix)]
        except WorkspaceError:
            continue  # one pack's unreadable history cannot hide another's digest
    if len(prefix) < 6 or not hits:
        raise WorkspaceError(f"{prefix} is neither a file nor a pack digest in the history of {ws} (at least 6 characters)")
    if len({e["digest"] for _, e in hits}) > 1:
        raise WorkspaceError(f"{prefix!r} matches more than one digest; give more of it")
    folder, entry = hits[0]
    if not entry.get("run"):
        raise WorkspaceError(f"digest {entry['digest'][:12]} was never run in this workspace; `terms run` it first")
    return ws / entry["run"] / "result.json"


def checkout(folder, src, prefix, current_digest, force):
    entries = history(folder)
    entry = find(entries, prefix, str(folder / "history.jsonl"))
    if not force:
        mine = folder / "history" / f"{str(current_digest)[:12]}.yaml"
        if current_digest is None or not mine.is_file() or mine.read_bytes() != pathlib.Path(src).read_bytes():
            raise WorkspaceError(f"{src} has changes no run or publish has recorded; run it first, or pass --force to discard them")
    subdir(folder, "history")
    snap = folder / "history" / f"{entry['digest'][:12]}.yaml"
    if snap.is_symlink() or not snap.is_file():
        raise WorkspaceError(f"{snap} is missing; that digest cannot be restored")
    _checked(pathlib.Path(src))
    shutil.copyfile(snap, src)
    return entry


def keep_transcript(folder, file, now):
    """Opt-in, private: a copy under private/ (0700, files 0600). No other verb reads or copies it."""
    private = subdir(folder, "private", 0o700)
    os.chmod(private, 0o700)
    stamp = f"transcript-{now.strftime('%Y%m%dT%H%M%S')}Z"
    suffix = pathlib.Path(file).suffix or ".txt"
    dest = private / f"{stamp}{suffix}"
    n = 1
    while dest.exists() or dest.is_symlink():
        n += 1
        dest = private / f"{stamp}-{n}{suffix}"
    try:
        data = pathlib.Path(file).read_bytes()
    except OSError as e:
        raise WorkspaceError(f"cannot read {file}: {e}")
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return dest


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)
