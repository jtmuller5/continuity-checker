"""What a judge cloning the repo has to be told.

The contest rules ask the repository to carry everything needed to run the
project. A dependency added later and never written down breaks that quietly:
the suite still passes on the machine that has the package, and the clone dies
on an ImportError.

So the claim here is: **every package `cinema/` imports is named in
requirements.txt, and the README says how to install them.** The import list is
read out of the source rather than kept by hand, so adding a dependency without
recording it turns this red.

Everything here reads files. Nothing is installed and nothing is billed.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "cinema"

# The distribution that provides each importable name. Two entries, and adding a
# third is the moment to think about whether the project wants it.
DISTRIBUTION = {"yaml": "pyyaml", "google": "google-genai"}


def imported_roots():
    """The top-level module every file in cinema/ imports."""
    roots = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def third_party(roots):
    """Whatever is neither the standard library nor a module of this project."""
    local = {path.stem for path in PACKAGE.rglob("*.py")}
    local.update(path.name for path in PACKAGE.iterdir() if path.is_dir())
    local.add("cinema")
    return {
        root
        for root in roots
        if root not in sys.stdlib_module_names and root not in local
    }


def requirement_names():
    """The distributions requirements.txt pins, lowercased, without versions."""
    names = {}
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        name, _, version = line.partition("==")
        names[name.strip().lower()] = version.strip()
    return names


class TestRequirements(unittest.TestCase):
    def test_every_imported_package_is_declared(self):
        pinned = requirement_names()
        for root in sorted(third_party(imported_roots())):
            self.assertIn(
                DISTRIBUTION.get(root, root),
                pinned,
                f"cinema/ imports {root!r} and requirements.txt does not name it",
            )

    def test_every_requirement_is_pinned(self):
        for name, version in requirement_names().items():
            self.assertTrue(version, f"{name} is not pinned to a version")

    def test_the_readme_says_how_to_install_them(self):
        readme = (ROOT / "README.md").read_text()
        # assertTrue, not assertIn: a failing assertIn prints the whole README.
        self.assertTrue(
            "pip install -r requirements.txt" in readme,
            "README.md does not say how to install the requirements",
        )
        self.assertTrue("git clone" in readme, "README.md does not say how to clone it")

    def test_the_offline_path_needs_only_pyyaml(self):
        """The claim the README makes, checked against the source.

        A judge with no Google Cloud account runs build, check and fix first. So
        google-genai may only be imported from inside a function — an import at
        the top of a module would be paid on every run, credential or not.
        """
        for path in sorted(PACKAGE.rglob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in tree.body:
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                self.assertNotIn(
                    "google",
                    [name.split(".")[0] for name in names],
                    f"{path.relative_to(ROOT)} imports google at module level",
                )


if __name__ == "__main__":
    unittest.main()
