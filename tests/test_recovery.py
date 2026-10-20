"""Crash-recovery snapshots are isolated from explicit project saves."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from planforge.recovery import clear_recovery_snapshot, list_recovery_snapshots, load_recovery_project, save_recovery_snapshot
from planforge.session import create_default_project


class RecoverySnapshotTests(unittest.TestCase):
    def test_snapshot_round_trip_and_clear_are_project_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = create_default_project()
            source = root / "Project with spaces.pfp"
            snapshot = save_recovery_snapshot(project, source, root=root)
            records, warnings = list_recovery_snapshots(root=root)
            self.assertEqual(warnings, [])
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].project_id, project.id)
            self.assertEqual(records[0].project_name, project.name)
            self.assertEqual(records[0].source_path, source)
            restored = load_recovery_project(snapshot.snapshot_path)
            self.assertEqual(restored.id, project.id)
            self.assertEqual([task.name for task in restored.tasks], [task.name for task in project.tasks])
            clear_recovery_snapshot(project.id, root=root)
            self.assertEqual(list_recovery_snapshots(root=root), ([], []))

    def test_corrupt_recovery_does_not_block_other_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = create_default_project()
            save_recovery_snapshot(project, root=root)
            bad = root / "recovery" / "recovery-corrupt.pfp"
            bad.write_text("not a database", encoding="utf-8")
            records, warnings = list_recovery_snapshots(root=root)
            self.assertEqual(len(records), 1)
            self.assertEqual(len(warnings), 1)


if __name__ == "__main__":
    unittest.main()
