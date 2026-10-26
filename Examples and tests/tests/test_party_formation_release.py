"""Exercise the real release tool only in temporary external fixtures."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import uuid
import shutil
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('formation_release', ROOT / 'tools/heroai_formation_release.py')
assert spec and spec.loader
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class RecoveryTests(unittest.TestCase):
    def test_relocated_bundle_uses_its_own_tool_and_keeps_receipt_paths(self) -> None:
        shutil.copyfile(ROOT / 'tools/heroai_formation_release.py', self.bundle / 'heroai_formation_release.py')
        relocated = self.bundle.with_name(self.bundle.name + '-relocated')
        shutil.copytree(self.bundle, relocated)
        self.bundle = relocated
        self.target = relocated / 'fixtures/mixed-runtime'
        before = self.snapshot()
        spec = importlib.util.spec_from_file_location(
            'relocated_formation_release', relocated / 'heroai_formation_release.py'
        )
        assert spec and spec.loader
        independent = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(independent)
        receipt = independent.deploy(relocated, self.target, self.approval, fixture=True)
        record = json.loads((receipt / 'installation.json').read_text())
        self.assertEqual(Path(record['bundle']), relocated)
        self.assertEqual(independent.restore(receipt, fixture=True), 'restored')
        self.assertEqual(self.snapshot(), before)
        moved_receipt = relocated / 'wrong-receipt-location'
        shutil.copytree(receipt, moved_receipt)
        with self.assertRaisesRegex(ValueError, 'Receipt must belong'):
            independent.restore(moved_receipt, fixture=True)

    def test_backup_change_after_global_preflight_is_not_restored(self) -> None:
        receipt = self.deploy()
        original = release.install_bytes
        damaged = release.FILES[1]
        first = release.FILES[0]

        def change_later_backup(path: Path, data: bytes, installation: str) -> None:
            original(path, data, installation)
            if path == self.target / first:
                (receipt / 'original' / damaged).write_bytes(b'changed after global preflight')

        with patch.object(release, 'install_bytes', change_later_backup):
            with self.assertRaisesRegex(RuntimeError, 'Backup integrity mismatch'):
                release.restore(receipt, fixture=True)
        self.assertEqual((self.target / first).read_bytes(), self.originals[first])
        self.assertEqual((self.target / damaged).read_bytes(), (self.bundle / 'artifact' / damaged).read_bytes())
        record = json.loads((receipt / 'installation.json').read_text())
        self.assertEqual(record['state'], 'rollback_failed')
        self.assertEqual(record['restored'], [first])
        self.assertEqual(record['rollback_pending'], damaged)

    def test_restore_verifies_written_bytes_and_final_new_file_absence(self) -> None:
        receipt = self.deploy()
        original = release.install_bytes

        def corrupt_destination(path: Path, data: bytes, installation: str) -> None:
            original(path, data, installation)
            path.write_bytes(b'simulated incorrect restoration')

        with patch.object(release, 'install_bytes', corrupt_destination):
            with self.assertRaisesRegex(RuntimeError, 'Restored file integrity mismatch'):
                release.restore(receipt, fixture=True)
        self.assertEqual(json.loads((receipt / 'installation.json').read_text())['state'], 'rollback_failed')

    def test_post_preflight_new_file_reappearance_prevents_success(self) -> None:
        receipt = self.deploy()
        original = release.install_bytes
        added = next(name for name, data in self.originals.items() if data is None)

        def reappear_after_removal(path: Path, data: bytes, installation: str) -> None:
            original(path, data, installation)
            if path == self.target / release.FILES[-1]:
                (self.target / added).write_bytes(b'reappeared')

        with patch.object(release, 'install_bytes', reappear_after_removal):
            with self.assertRaisesRegex(RuntimeError, 'Final rollback verification failed'):
                release.restore(receipt, fixture=True)

    def setUp(self) -> None:
        # Retain inspectable recovery fixtures; avoid TemporaryDirectory's Windows
        # private ACL, which is inaccessible under the managed test identity.
        self.bundle = Path(tempfile.gettempdir()) / ('HeroAI-release-fixture-' + uuid.uuid4().hex)
        self.bundle.mkdir()
        self.target = self.bundle / 'fixtures' / 'mixed-runtime'
        self.target.mkdir(parents=True)
        (self.target / '.formation-fixture').touch()
        self.originals: dict[str, bytes | None] = {}
        files = {}
        for index, relative in enumerate(release.FILES):
            artifact = self.bundle / 'artifact' / relative
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(f'new implementation {index}\r\n'.encode())
            before = None if 'PartyFormation' in relative else f'mixed personal original {index}\r\n'.encode()
            destination = self.target / relative
            if before is not None:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(before)
            self.originals[relative] = before
            files[relative] = {
                'expected_sha256': release.digest(destination),
                'deployed_sha256': release.digest(artifact),
            }
        (self.target / 'unrelated.txt').write_bytes(b'personal changes\x00preserve exactly')
        (self.bundle / 'release.json').write_text(json.dumps({'schema': 1, 'files': files}), encoding='utf-8')
        self.approval = release.digest(self.bundle / 'release.json')

    def snapshot(self) -> dict[str, bytes]:
        return {
            str(path.relative_to(self.target)): path.read_bytes() for path in self.target.rglob('*') if path.is_file()
        }

    def deploy(self, **kwargs: int | None) -> Path:
        return release.deploy(self.bundle, self.target, self.approval, fixture=True, **kwargs)

    def test_deploy_exact_backup_restore_new_file_removal_and_idempotence(self) -> None:
        before = self.snapshot()
        receipt = self.deploy()
        record = json.loads((receipt / 'installation.json').read_text())
        self.assertEqual(record['state'], 'installed')
        for relative, data in self.originals.items():
            if data is not None:
                self.assertEqual((receipt / 'original' / relative).read_bytes(), data)
        self.assertEqual(release.restore(receipt, fixture=True), 'restored')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(release.restore(receipt, fixture=True), 'already restored')

    def test_hash_mismatch_and_manifest_approval_preflight_every_file(self) -> None:
        for mode in ('baseline', 'artifact', 'approval'):
            with self.subTest(mode=mode):
                before = self.snapshot()
                path = (self.target if mode == 'baseline' else self.bundle / 'artifact') / release.FILES[-1]
                old = path.read_bytes()
                if mode != 'approval':
                    path.write_bytes(b'newer work')
                expected = self.snapshot()
                try:
                    with self.assertRaises(RuntimeError):
                        release.deploy(
                            self.bundle, self.target, 'wrong' if mode == 'approval' else self.approval, fixture=True
                        )
                    self.assertEqual(self.snapshot(), expected)
                finally:
                    path.write_bytes(old)
                self.assertEqual(self.snapshot(), before)

    def test_rollback_refuses_later_edits_before_restoring_any_file(self) -> None:
        receipt = self.deploy()
        (self.target / release.FILES[-1]).write_bytes(b'later personal improvement')
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'Later edit'):
            release.restore(receipt, fixture=True)
        self.assertEqual(self.snapshot(), before)

    def test_failed_installation_restores_only_this_installation(self) -> None:
        before = self.snapshot()
        for index in (0, 1, 5, len(release.FILES) - 1):
            with self.subTest(fail_after=index):
                with self.assertRaisesRegex(RuntimeError, 'original files restored'):
                    self.deploy(fail_after=index)
                self.assertEqual(self.snapshot(), before)

    def test_backup_damage_refuses_entire_rollback(self) -> None:
        receipt = self.deploy()
        (receipt / 'original' / release.FILES[0]).write_bytes(b'damaged backup')
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'backup damaged'):
            release.restore(receipt, fixture=True)
        self.assertEqual(self.snapshot(), before)

    def test_failure_after_replace_before_completion_journal_is_recoverable(self) -> None:
        before = self.snapshot()
        original = release.install_bytes
        calls = 0

        def fail_once(path: Path, data: bytes, installation: str) -> None:
            nonlocal calls
            original(path, data, installation)
            calls += 1
            if calls == 2:
                raise OSError('simulated failure after atomic replacement')

        with patch.object(release, 'install_bytes', fail_once):
            with self.assertRaisesRegex(RuntimeError, 'original files restored'):
                self.deploy()
        self.assertEqual(self.snapshot(), before)
        latest = json.loads((self.bundle / 'latest-installation.json').read_text())
        self.assertEqual(release.restore(Path(latest['receipt']), fixture=True), 'already restored')

    def test_fixture_escape_and_path_traversal_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, 'permanent Py4GW-Recovery'):
            release.check_target(self.bundle, release.TESTS_ROOT, False)
        with self.assertRaises(ValueError):
            release.deploy(self.bundle, release.TESTS_ROOT, self.approval, fixture=True)
        with self.assertRaises(ValueError):
            release.safe_path(self.target, '../unrelated.txt')


if __name__ == '__main__':
    unittest.main(verbosity=2)
