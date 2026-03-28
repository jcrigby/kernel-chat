"""Extract structured commit records from a Linux kernel git repository.

Uses a sentinel-delimited git log format to reliably parse multi-line
commit bodies, numstat file changes, and merge detection.
"""

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

# Sentinels — chosen to never appear in real commit data
_COMMIT_START = "---KERNELCHAT_COMMIT_START---"
_COMMIT_END = "---KERNELCHAT_COMMIT_END---"

# git log format: fields separated by newlines, bookended by sentinels.
# %H  = hash
# %aI = author date ISO 8601
# %cI = committer date ISO 8601
# %aN = author name
# %aE = author email
# %cN = committer name
# %cE = committer email
# %P  = parent hashes (space-separated; >1 means merge)
# %s  = subject
# %b  = body
_GIT_LOG_FORMAT = (
    f"{_COMMIT_START}%n%H%n%aI%n%cI%n%aN%n%aE%n%cN%n%cE%n%P%n%s%n%b{_COMMIT_END}"
)


@dataclass
class CommitRecord:
    """A single parsed commit."""

    hash: str
    authored_date: datetime
    committed_date: datetime
    author_name: str
    author_email: str
    committer_name: str
    committer_email: str
    subject: str
    body: str
    files_changed: list[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    merge: bool = False


def _parse_numstat_line(line: str) -> tuple[int, int, str] | None:
    """Parse a numstat line: '<ins>\\t<del>\\t<path>'.

    Returns (insertions, deletions, filepath) or None if unparseable.
    Binary files show '-' for ins/del — we record them as 0/0.
    Renames show 'old => new' or '{old => new}' — we take the full string.
    """
    parts = line.split("\t", 2)
    if len(parts) != 3:
        return None
    ins_str, del_str, path = parts
    ins = int(ins_str) if ins_str != "-" else 0
    del_ = int(del_str) if del_str != "-" else 0
    # For renames like 'path/{old => new}/file', keep as-is; the load
    # step can normalise if needed.
    return ins, del_, path


def extract_commits(
    repo_path: str | Path,
    *,
    after: str | None = None,
    limit: int | None = None,
) -> Iterator[CommitRecord]:
    """Stream parsed CommitRecords from the git log of *repo_path*.

    Parameters
    ----------
    repo_path:
        Path to the kernel git repo.
    after:
        If given, only yield commits after this date (ISO 8601 string).
        Useful for incremental ingestion.
    limit:
        If given, stop after this many commits (for testing).
    """
    repo_path = Path(repo_path)
    cmd = [
        "git", "-C", str(repo_path),
        "log",
        f"--format={_GIT_LOG_FORMAT}",
        "--numstat",
        "--encoding=UTF-8",
    ]
    if after:
        cmd.append(f"--after={after}")

    logger.info("Running: %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",  # handle Latin-1 in old commits
    )
    assert proc.stdout is not None

    count = 0
    commit_lines: list[str] = []
    numstat_lines: list[str] = []
    in_commit = False

    for raw_line in proc.stdout:
        line = raw_line.rstrip("\n")

        if line == _COMMIT_START:
            # Yield the *previous* commit (commit_lines + numstat collected
            # between its COMMIT_END and this COMMIT_START).
            if commit_lines:
                record = _build_record(commit_lines, numstat_lines)
                if record is not None:
                    yield record
                    count += 1
                    if limit and count >= limit:
                        proc.terminate()
                        return
            commit_lines = []
            numstat_lines = []
            in_commit = True
            continue

        if in_commit:
            if _COMMIT_END in line:
                before = line.split(_COMMIT_END, 1)[0]
                if before:
                    commit_lines.append(before)
                in_commit = False
            else:
                commit_lines.append(line)
        else:
            # Between COMMIT_END and next COMMIT_START: numstat lines
            if line:
                numstat_lines.append(line)

    # Last commit
    if commit_lines:
        record = _build_record(commit_lines, numstat_lines)
        if record is not None:
            yield record

    proc.wait()
    if proc.returncode and proc.returncode != -15:  # -15 = SIGTERM from limit
        stderr = proc.stderr.read() if proc.stderr else ""
        logger.error("git log exited with %d: %s", proc.returncode, stderr)


def _build_record(
    commit_lines: list[str], numstat_lines: list[str]
) -> CommitRecord | None:
    """Parse the accumulated lines into a CommitRecord."""
    # We expect at least 9 header lines: hash, adate, cdate, aname, aemail,
    # cname, cemail, parents, subject. Body follows (may be empty).
    if len(commit_lines) < 9:
        logger.warning("Short commit block (%d lines), skipping", len(commit_lines))
        return None

    hash_ = commit_lines[0]
    try:
        authored_date = datetime.fromisoformat(commit_lines[1])
        committed_date = datetime.fromisoformat(commit_lines[2])
    except ValueError as e:
        logger.warning("Bad date in commit %s: %s", hash_, e)
        return None

    author_name = commit_lines[3]
    author_email = commit_lines[4]
    committer_name = commit_lines[5]
    committer_email = commit_lines[6]
    parents = commit_lines[7]
    subject = commit_lines[8]
    body = "\n".join(commit_lines[9:]).strip()

    merge = len(parents.split()) > 1

    # Parse numstat
    files: list[str] = []
    total_ins = 0
    total_del = 0
    for ns_line in numstat_lines:
        parsed = _parse_numstat_line(ns_line)
        if parsed:
            ins, del_, path = parsed
            total_ins += ins
            total_del += del_
            files.append(path)

    return CommitRecord(
        hash=hash_,
        authored_date=authored_date,
        committed_date=committed_date,
        author_name=author_name,
        author_email=author_email,
        committer_name=committer_name,
        committer_email=committer_email,
        subject=subject,
        body=body,
        files_changed=files,
        insertions=total_ins,
        deletions=total_del,
        merge=merge,
    )


if __name__ == "__main__":
    import sys
    from src.utils.config import KERNEL_REPO_PATH
    from src.utils.logging import setup_logging

    setup_logging()
    count = 0
    for commit in extract_commits(KERNEL_REPO_PATH, limit=10):
        print(f"{commit.hash[:12]} {commit.authored_date.date()} "
              f"{'M' if commit.merge else ' '} {commit.subject[:80]}")
        count += 1
    print(f"\n{count} commits extracted.")
