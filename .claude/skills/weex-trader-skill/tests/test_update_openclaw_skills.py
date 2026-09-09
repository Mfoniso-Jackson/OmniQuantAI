#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
UPDATE_SCRIPT = ROOT / "scripts" / "update_openclaw_skills.sh"
SKILLS = ("weex-trader-skill", "weex-analysis-skill", "weex-monitor-skill")


class OpenClawUpdateTests(unittest.TestCase):
    def write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, root: Path, message: str) -> None:
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=WEEX Tests",
                "-c",
                "user.email=tests@example.invalid",
                "commit",
                "-qm",
                message,
            ],
            cwd=root,
            check=True,
        )

    def source_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        for skill in SKILLS:
            self.write(
                root / "skills" / skill / "SKILL.md",
                f"---\nname: {skill}\ndescription: Test fixture.\n---\n",
            )
        target = root / UPDATE_SCRIPT.relative_to(REPO_ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(UPDATE_SCRIPT, target)
        target.chmod(0o755)
        self.commit(root, "fixture")

    def env(self, root: Path, source: Path) -> tuple[dict[str, str], Path, Path, Path]:
        fake_bin = root / "bin"
        fake_bin.mkdir()
        log = root / "openclaw.log"
        self.write(
            fake_bin / "openclaw",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"printf '%s\\n' \"$*\" >> {str(log)!r}\n",
        )
        (fake_bin / "openclaw").chmod(0o755)
        openclaw_root = root / ".openclaw"
        repo_dir = openclaw_root / "skill-repos" / "weex-agent-skills-ai-wars"
        skills_dir = openclaw_root / "skills"
        updater_link = root / "bin-link" / "update-weex-openclaw-skills.sh"
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(root),
                "PATH": f"{fake_bin}{os.pathsep}{environment.get('PATH', '')}",
                "WEEX_OPENCLAW_REPO_URL": str(source),
                "WEEX_OPENCLAW_BRANCH": "main",
                "WEEX_OPENCLAW_REPO_DIR": str(repo_dir),
                "WEEX_OPENCLAW_SKILLS_DIR": str(skills_dir),
                "WEEX_OPENCLAW_BIN_LINK": str(updater_link),
            }
        )
        return environment, repo_dir, skills_dir, log

    def run_update(self, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(UPDATE_SCRIPT), "--dev"],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_dev_update_links_all_ai_wars_skills_and_keeps_stable_updater(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "source"
            source.mkdir()
            self.source_repo(source)
            environment, repo_dir, skills_dir, log = self.env(root, source)

            result = self.run_update(environment)

            self.assertEqual(result.returncode, 0, f"{result.stdout}\n{result.stderr}")
            for skill in SKILLS:
                link = skills_dir / skill
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), (repo_dir / "skills" / skill).resolve())
            self.assertTrue((root / ".openclaw" / "update-weex-openclaw-skills.sh").is_file())
            self.assertEqual(
                log.read_text(encoding="utf-8").splitlines(),
                ["skills list --eligible", "skills info weex-trader-skill", "skills check"],
            )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_failed_openclaw_check_restores_previous_checkout_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "source"
            source.mkdir()
            self.source_repo(source)
            environment, repo_dir, skills_dir, _log = self.env(root, source)
            first = self.run_update(environment)
            self.assertEqual(first.returncode, 0, f"{first.stdout}\n{first.stderr}")
            old_commit = subprocess.check_output(
                ["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True
            ).strip()

            self.write(source / "UPDATED", "rollback candidate\n")
            self.commit(source, "rollback candidate")
            fake_openclaw = Path(environment["PATH"].split(os.pathsep)[0]) / "openclaw"
            self.write(fake_openclaw, "#!/usr/bin/env bash\nexit 17\n")
            fake_openclaw.chmod(0o755)

            second = self.run_update(environment)

            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(repo_dir), "rev-parse", "HEAD"], text=True
                ).strip(),
                old_commit,
            )
            self.assertFalse((repo_dir / "UPDATED").exists())
            for skill in SKILLS:
                self.assertEqual(
                    (skills_dir / skill).resolve(), (repo_dir / "skills" / skill).resolve()
                )

    def test_production_rejects_repository_override_without_dev_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            environment, repo_dir, _skills_dir, _log = self.env(Path(tempdir), Path(tempdir))
            result = subprocess.run(
                ["bash", str(UPDATE_SCRIPT)],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--dev", result.stderr)
            self.assertFalse(repo_dir.exists())


if __name__ == "__main__":
    unittest.main()
