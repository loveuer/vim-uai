import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import vim_uai_context as context


class ProjectContextTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="vim-uai-project-")
        self.addCleanup(self.directory.cleanup)
        self.base = pathlib.Path(self.directory.name).resolve()
        self.root = self.base / "project 中文"
        self.root.mkdir()

    def write(self, relative, text="content\n"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def collect(self, filename="src/main.py", **options):
        edit = {"filepath": str(self.root / filename) if filename else "", "workdir": str(self.root)}
        return context.collect_project_context(edit, dict(enabled=True, **options))

    def test_git_root_wins_over_nested_manifest_and_recognizes_worktree_file(self):
        for git_is_file in (False, True):
            with self.subTest(git_is_file=git_is_file):
                marker = self.root / ".git"
                if marker.exists():
                    marker.rmdir()
                if git_is_file:
                    marker.write_text("gitdir: /some/other/git-directory\n")
                else:
                    marker.mkdir()
                self.write("packages/app/package.json", '{"name":"app"}')
                source = self.write("packages/app/src/main.py")
                root, kind = context.find_root(source, source.parent)
                self.assertEqual(root, self.root)
                self.assertEqual(kind, ".git")

    def test_nearest_manifest_without_git(self):
        self.write("pyproject.toml", "[project]\n")
        self.write("packages/app/go.mod", "module example/app\n")
        source = self.write("packages/app/src/main.go")
        root, kind = context.find_root(source, source.parent)
        self.assertEqual(root, self.root / "packages/app")
        self.assertEqual(kind, "go.mod")

    def test_workdir_unnamed_and_external_file_fallback(self):
        project = self.collect(filename="")
        self.assertEqual(project["root"], str(self.root))
        self.assertEqual(project["root_source"], "workdir")
        self.assertIsNone(project["current_file"])
        external = self.base / "outside" / "new.py"
        external.parent.mkdir()
        root, kind = context.find_root(external, self.root)
        self.assertEqual(root, external.parent)
        self.assertEqual(kind, "file_directory")
        new_file = self.root / "not-created-yet" / "new.py"
        self.assertEqual(context.find_root(new_file, self.root), (self.root, "workdir"))

    def test_relative_override_and_file_outside_root(self):
        alternate = self.root / "alternate"
        alternate.mkdir()
        project = self.collect(root="alternate")
        self.assertEqual(project["root"], str(alternate))
        self.assertEqual(project["root_source"], "configured")
        self.assertIsNone(project["current_file"])

    def test_tree_depth_exclusions_and_symlinks(self):
        self.write("src/main.py")
        self.write("src/deep/hidden.py")
        self.write(".git/config")
        self.write("node_modules/dependency/index.js")
        self.write("vendor/third_party.go")
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "unrelated.py").write_text("unrelated")
        (self.root / "linked").symlink_to(outside, target_is_directory=True)
        project = self.collect(max_depth=2)
        self.assertIn("src/main.py", project["tree"])
        self.assertIn("src/deep/", project["tree"])
        self.assertIn("linked", project["tree"])
        self.assertNotIn("src/deep/hidden.py", project["tree"])
        self.assertFalse(any("node_modules" in path or "vendor" in path or ".git" in path for path in project["tree"]))
        self.assertFalse(any("unrelated.py" in path for path in project["tree"]))
        self.assertTrue(project["tree_truncated"])

    def test_tree_entry_and_scan_limits(self):
        for index in range(80):
            self.write("file-{:03}.py".format(index))
        project = self.collect(max_entries=5)
        self.assertEqual(len(project["tree"]), 5)
        self.assertTrue(project["tree_truncated"])

    def test_applicable_rules_manifests_and_readme(self):
        self.write(".git", "gitdir: elsewhere")
        self.write("AGENTS.md", "Root rules\n")
        self.write("src/AGENTS.md", "Source rules\n")
        self.write("other/AGENTS.md", "Unrelated rules\n")
        self.write("go.mod", "module example/project\n\ngo 1.23\n")
        self.write("README.md", "Project overview\n")
        self.write("src/main.py", "source is supplied by Vim\n")
        self.write("src/other.py", "Do not automatically read arbitrary source files\n")
        project = self.collect()
        files = {file["path"]: file for file in project["files"]}
        self.assertEqual(list(files)[:2], ["AGENTS.md", "src/AGENTS.md"])
        self.assertEqual(files["go.mod"]["content"], "module example/project\n\ngo 1.23\n")
        self.assertEqual(files["go.mod"]["start_line"], 1)
        self.assertEqual(files["go.mod"]["end_line"], 3)
        self.assertIn("README.md", files)
        self.assertNotIn("other/AGENTS.md", files)
        self.assertNotIn("src/other.py", files)
        self.assertEqual(project["current_file"], "src/main.py")

    def test_source_manifest_not_replaced_by_stale_disk_content(self):
        self.write("go.mod", "stale disk content")
        project = self.collect(filename="go.mod")
        self.assertEqual(project["root_source"], "go.mod")
        self.assertNotIn("go.mod", [file["path"] for file in project["files"]])

    def test_excerpt_budgets_and_symlinked_documents(self):
        self.write("AGENTS.md", "a" * 9000)
        self.write("go.mod", "b" * 9000)
        self.write("package.json", "c" * 9000)
        self.write("pyproject.toml", "d" * 9000)
        self.write("README.md", "not enough budget for this file")
        project = self.collect()
        self.assertLessEqual(sum(len(file["content"].encode()) for file in project["files"]), 32768)
        self.assertTrue(all(file["truncated"] for file in project["files"]))
        self.assertTrue(project["files_truncated"])
        (self.root / "README.md").unlink()
        outside = self.base / "outside.md"
        outside.write_text("must not follow this link")
        (self.root / "README.md").symlink_to(outside)
        files, _, _ = context.context_files(self.root, None)
        self.assertNotIn("README.md", [file["path"] for file in files])

    def test_disable_and_invalid_settings(self):
        self.assertIsNone(context.collect_project_context({}, {"enabled": False}))
        for options in ({"max_depth": 0}, {"max_entries": -1}, {"root": "nonexistent"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.collect(**options)


if __name__ == "__main__":
    unittest.main()
