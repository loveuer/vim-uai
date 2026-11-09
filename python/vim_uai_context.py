"""Bounded project context collection, run in the asynchronous request worker."""

import os
from collections import deque
from pathlib import Path


VCS_MARKERS = (".git", ".hg", ".svn")
MANIFESTS = (
    "go.work", "go.mod", "package.json", "pyproject.toml", "Cargo.toml",
    "pom.xml", "build.gradle", "build.gradle.kts", "composer.json", "Gemfile",
    "mix.exs", "deno.json", "CMakeLists.txt",
)
CONFIG_FILES = (".editorconfig", "tsconfig.json", "ruff.toml", ".golangci.yml", "Makefile")
EXCLUDED_DIRS = frozenset((
    ".git", ".hg", ".svn", "node_modules", "vendor", ".venv", "venv", "__pycache__",
    ".cache", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", "dist", "build", "target",
))
MAX_CONTEXT_FILES = 12
MAX_FILE_BYTES = 8192
MAX_TOTAL_FILE_BYTES = 32768


def relative_path(path, root):
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def find_root(filepath, workdir, override=""):
    if override:
        root = Path(override).expanduser()
        root = (root if root.is_absolute() else workdir / root).resolve()
        if not root.is_dir():
            raise ValueError("g:vim_uai_project_root must point to an existing directory.")
        return root, "configured"
    start = filepath.parent if filepath else workdir
    directories = (start, *start.parents)
    # Prefer the repository boundary, including .git files used by worktrees.
    for directory in directories:
        for marker in VCS_MARKERS:
            if (directory / marker).exists():
                return directory, marker
    for directory in directories:
        for marker in MANIFESTS:
            if (directory / marker).is_file():
                return directory, marker
    if workdir.is_dir() and relative_path(start, workdir) is not None:
        return workdir, "workdir"
    for directory in directories:
        if directory.is_dir():
            return directory, "file_directory"
    raise ValueError("Could not locate a project directory.")


def directory_tree(root, max_entries, max_depth):
    result = []
    queue = deque([(root, 0)])
    truncated = False
    unavailable = []
    scanned = 0
    scan_budget = max_entries * 4
    while queue:
        directory, depth = queue.popleft()
        entries = []
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    scanned += 1
                    if scanned > scan_budget:
                        truncated = True
                        break
                    if entry.name in EXCLUDED_DIRS:
                        continue
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    entries.append((is_dir, entry.name, Path(entry.path)))
        except OSError:
            unavailable.append(relative_path(directory, root) or ".")
            continue
        for is_dir, name, path in sorted(entries, key=lambda item: (not item[0], item[1])):
            if len(result) >= max_entries:
                return result, True, unavailable
            result.append(relative_path(path, root) + ("/" if is_dir else ""))
            if is_dir:
                if depth + 1 < max_depth:
                    queue.append((path, depth + 1))
                else:
                    truncated = True
        if scanned > scan_budget:
            break
    return result, truncated, unavailable


def context_files(root, filepath):
    directories = [root]
    if filepath and relative_path(filepath, root) is not None:
        directories = list(reversed((filepath.parent, *filepath.parent.parents)))
        directories = [path for path in directories if relative_path(path, root) is not None]
    candidates = [directory / "AGENTS.md" for directory in directories]
    candidates += [directory / name for directory in reversed(directories) for name in MANIFESTS]
    candidates += [root / "README.md", root / "README.rst", root / "README"]
    candidates += [directory / name for directory in reversed(directories) for name in CONFIG_FILES]
    files, unavailable = [], []
    remaining = MAX_TOTAL_FILE_BYTES
    truncated = False
    for path in candidates:
        try:
            # The source buffer is supplied by Vim; never substitute a stale disk copy.
            if path.is_symlink() or path.resolve() == filepath or relative_path(path.resolve(), root) is None:
                continue
            if not path.is_file():
                continue
            if not remaining or len(files) >= MAX_CONTEXT_FILES:
                truncated = True
                break
            limit = min(MAX_FILE_BYTES, remaining)
            with path.open("rb") as stream:
                raw = stream.read(limit + 1)
            if b"\x00" in raw:
                unavailable.append(relative_path(path, root))
                continue
            content = raw[:limit].decode("utf-8", errors="replace").replace("\r\n", "\n")
            files.append({"path": relative_path(path, root), "start_line": 1,
                          "end_line": len(content.splitlines()), "content": content,
                          "truncated": len(raw) > limit})
            remaining -= min(len(raw), limit)
        except OSError:
            unavailable.append(relative_path(path, root))
    return files, truncated, unavailable


def collect_project_context(edit, options):
    if not options.get("enabled", False):
        return None
    max_entries = options.get("max_entries", 200)
    max_depth = options.get("max_depth", 3)
    for name, value in (("max_entries", max_entries), ("max_depth", max_depth)):
        if type(value) is not int or value < 1:
            raise ValueError("g:vim_uai_project_{} must be a positive integer.".format(name))
    workdir = Path(edit["workdir"]).resolve()
    filepath = Path(edit["filepath"]).resolve() if edit.get("filepath") else None
    root, source = find_root(filepath, workdir, options.get("root", ""))
    tree, tree_truncated, unreadable_dirs = directory_tree(root, max_entries, max_depth)
    files, files_truncated, unreadable_files = context_files(root, filepath)
    return {
        "root": str(root), "root_source": source,
        "current_file": relative_path(filepath, root) if filepath else None,
        "tree": tree, "tree_truncated": tree_truncated,
        "max_depth": max_depth, "max_entries": max_entries,
        "files": files, "files_truncated": files_truncated,
        "unavailable_directories": unreadable_dirs, "unavailable_files": unreadable_files,
    }
