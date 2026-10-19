"""Smoke tests for the real Tkinter window.

These run only where Tk and a display are available (for example on a
desktop, or under Xvfb on Linux). They are skipped everywhere else, so the
headless suite in test_session.py always runs.
"""

from __future__ import annotations

import unittest

try:
    import tkinter as tk

    _root = tk.Tk()
    _root.withdraw()
    _root.destroy()
    TK_AVAILABLE = True
    TK_ERROR = ""
except Exception as exc:  # ImportError, TclError (no display)
    TK_AVAILABLE = False
    TK_ERROR = str(exc)


@unittest.skipUnless(TK_AVAILABLE, f"Tkinter window not available: {TK_ERROR}")
class DesktopWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        from planforge.gui.app import PlanForgeApp

        self.app = PlanForgeApp()
        self.app.withdraw()

    def tearDown(self) -> None:
        self.app.destroy()

    def test_every_tab_renders_the_default_project(self) -> None:
        self.app.refresh_all()
        for index in range(len(self.app.notebook.tabs())):
            self.app.notebook.select(index)
            self.app.update_idletasks()
        self.assertEqual(self.app.views["overview"].metrics["Tasks"].get(), "4")

    def test_timeline_zoom_levels_draw(self) -> None:
        timeline = self.app.views["timeline"]
        for zoom in ("Days", "Weeks", "Months"):
            timeline.zoom_var.set(zoom)
            timeline.refresh()
            self.assertGreater(len(self.app.views["timeline"].chart.find_all()), 0)

    def test_theme_toggle_keeps_views_consistent(self) -> None:
        before = self.app.theme_name
        self.app.toggle_theme()
        self.assertNotEqual(self.app.theme_name, before)
        self.app.toggle_theme()
        self.assertEqual(self.app.theme_name, before)

    def test_task_editor_saves_through_session(self) -> None:
        from planforge.gui.dialogs import TaskDialog

        task = self.app.session.project.tasks[0]
        dialog = TaskDialog(self.app, self.app.session, task.id)
        dialog.name_var.set("Edited in window")
        dialog.on_ok()
        self.assertTrue(dialog.result, dialog.error_var.get())
        self.assertEqual(task.name, "Edited in window")


if __name__ == "__main__":
    unittest.main()
