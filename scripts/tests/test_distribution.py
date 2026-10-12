"""No real installers are used: fixtures are isolated in temporary directories."""

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assemble_distribution as distribution
from collect_native_artifacts import TARGETS


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "runtime").mkdir()
        (self.root / "runtime/pyproject.toml").write_text(
            '[project]\nversion="0.1.0"\n'
        )
        (self.root / "docs").mkdir()
        (self.root / "docs/PLATFORM_BUILDS.md").write_text("Test guide")
        self.location = patch.object(
            distribution,
            "__file__",
            str(self.root / "scripts/assemble_distribution.py"),
        )
        self.location.start()

    def tearDown(self):
        self.location.stop()
        self.temp.cleanup()

    def fixtures(self):
        for target, suffixes in TARGETS.items():
            directory = self.root / "build/downloaded-native" / f"nexus-{target}"
            directory.mkdir(parents=True)
            records = []
            for suffix in suffixes:
                name = "test-fixture" + suffix
                content = f"Test fixture, not installer: {target}".encode()
                (directory / name).write_bytes(content)
                records.append(
                    {
                        "name": name,
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
            (directory / "manifest.json").write_text(
                json.dumps(
                    {"target": target, "version": "0.1.0", "installers": records}
                )
            )
            (directory / "INSTALL.md").write_text("Fixture")

    def test_missing_platform_blocks_output(self):
        with self.assertRaises(FileNotFoundError):
            distribution.main()
        self.assertFalse((self.root / "build/distribution").exists())

    def test_modified_installer_blocks_output(self):
        self.fixtures()
        next((self.root / "build/downloaded-native").rglob("*.msi")).write_bytes(
            b"tampered"
        )
        with self.assertRaisesRegex(SystemExit, "checksum mismatch"):
            distribution.main()
        self.assertFalse((self.root / "build/distribution").exists())

    def test_complete_bundle_contains_source_docs_and_all_platforms(self):
        self.fixtures()

        def fake_git(command, **kwargs):
            output = Path(
                next(
                    arg.split("=", 1)[1]
                    for arg in command
                    if arg.startswith("--output=")
                )
            )
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("fixture.txt", "Test archive")

        with patch.object(distribution.subprocess, "run", side_effect=fake_git):
            distribution.main()
        bundle = self.root / "build/distribution/nexus-0.1.0-all-platforms.zip"
        with zipfile.ZipFile(bundle) as archive:
            for target in TARGETS:
                self.assertIn(f"platforms/{target}/manifest.json", archive.namelist())
            self.assertIn("nexus-0.1.0-source.zip", archive.namelist())
            self.assertIn("nexus-0.1.0-documentation.zip", archive.namelist())
            self.assertIsNone(archive.testzip())
        self.assertEqual(
            (bundle.parent / "SHA256SUMS.txt").read_text().split()[0],
            hashlib.sha256(bundle.read_bytes()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
