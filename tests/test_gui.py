"""Smoke and strict widget-option tests for the PlanForge Tkinter GUI.

``DesktopWindowTests`` exercises a real ``tk.Tk`` window whenever Tkinter and a
display are available. ``HeadlessStrictTkGuiTests`` runs when a display is not
available, validating every widget/menu option against Tcl/Tk 8.6's strict
option sets so regressions like ``add_cascade(..., postcommand=...)`` or
missing imports inside ``planforge.gui`` are caught in headless CI too.
"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

FIXTURES = Path(__file__).resolve().parent / "fixtures"

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
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._config_patch = patch("planforge.config.CONFIG_FILE", self.tmp / "PlanForge.conf")
        self._config_dir_patch = patch("planforge.config.CONFIG_DIR", self.tmp)
        self._recovery_dir_patch = patch("planforge.recovery.CONFIG_DIR", self.tmp)
        self._theme_dir_patch = patch("planforge.theme_library.CONFIG_DIR", self.tmp)
        self._config_patch.start()
        self._config_dir_patch.start()
        self._recovery_dir_patch.start()
        self._theme_dir_patch.start()

        from planforge.gui.app import PlanForgeApp

        self.app = PlanForgeApp()
        self.app.withdraw()

    def tearDown(self) -> None:
        self.app.destroy()
        self._theme_dir_patch.stop()
        self._recovery_dir_patch.stop()
        self._config_dir_patch.stop()
        self._config_patch.stop()
        self._tmp.cleanup()

    def test_every_tab_renders_the_default_project(self) -> None:
        self.app.refresh_all()
        for index in range(len(self.app.notebook.tabs())):
            self.app.notebook.select(index)
            self.app.update_idletasks()
        self.assertEqual(self.app.views["overview"].metrics["Tasks"].get(), "4")

    def test_recent_and_layout_menus_use_menu_postcommand_and_populate(self) -> None:
        self.assertTrue(bool(self.app.recent_menu.cget("postcommand")))
        self.assertTrue(bool(self.app.layout_menu.cget("postcommand")))
        self.app._populate_recent_menu()
        self.app._populate_layout_menu()
        self.assertEqual(self.app.recent_menu.index("end"), 0)
        self.assertGreaterEqual(self.app.layout_menu.index("end"), 2)

    def test_save_and_recovery_autosave_work_from_window(self) -> None:
        target = self.tmp / "window_save.pfp"
        self.app.session.add_task("Saved from GUI")
        self.assertGreater(self.app._recovery_interval_ms(), 0)
        self.app._autosave_recovery()
        self.assertTrue(self.app._save_to(target))
        self.assertTrue(target.is_file())
        self.assertFalse(self.app.session.dirty)
        self.app._populate_recent_menu()
        self.assertEqual(self.app.recent_menu.index("end"), 2)

    def test_timeline_zoom_levels_draw(self) -> None:
        timeline = self.app.views["timeline"]
        for zoom in ("Days", "Weeks", "Months"):
            timeline.zoom_var.set(zoom)
            timeline.refresh()
            self.assertGreater(len(self.app.views["timeline"].chart.find_all()), 0)

    def test_new_toolbar_button_starts_a_blank_project(self) -> None:
        self.app.new_button.invoke()
        self.assertEqual(self.app.session.project.name, "Untitled project")
        self.assertEqual(self.app.session.project.tasks, [])

    def test_ctrl_n_works_while_a_child_widget_has_focus(self) -> None:
        self.app.deiconify()
        entry = tk.Entry(self.app)
        entry.pack()
        self.app.update()
        entry.focus_force()
        self.app.update()
        entry.event_generate("<Control-n>")
        self.app.update()
        self.assertEqual(self.app.session.project.name, "Untitled project")
        self.assertEqual(self.app.session.project.tasks, [])
        entry.destroy()
        self.app.withdraw()

    def test_theme_toggle_cycles_built_ins_without_changing_project(self) -> None:
        from planforge.config import THEMES

        before = self.app.theme_name
        project_id = self.app.session.project.id
        if before in THEMES:
            for _ in THEMES:
                self.app.toggle_theme()
            self.assertEqual(self.app.theme_name, before)
        else:
            self.app.toggle_theme()
            self.assertEqual(self.app.theme_name, THEMES[0])
            self.app.set_theme(before)
        self.assertEqual(self.app.session.project.id, project_id)

    def test_builtin_palettes_cover_theme_editor_colors(self) -> None:
        from planforge.gui.theme import PALETTES
        from planforge.theme_library import PALETTE_KEYS

        for palette in PALETTES.values():
            self.assertEqual(set(palette), set(PALETTE_KEYS))
            self.assertTrue(all(len(value) == 7 and value.startswith("#") for value in palette.values()))

    def test_task_and_gantt_context_menus_exist(self) -> None:
        tasks = self.app.views["tasks"]
        timeline = self.app.views["timeline"]
        self.assertGreaterEqual(tasks.context_menu.index("end"), 3)
        self.assertGreaterEqual(timeline.context_menu.index("end"), 1)

    def test_task_editor_saves_through_session(self) -> None:
        from planforge.gui.dialogs import TaskDialog

        task = self.app.session.project.tasks[0]
        dialog = TaskDialog(self.app, self.app.session, task.id)
        dialog.name_var.set("Edited in window")
        dialog.on_ok()
        self.assertTrue(dialog.result, dialog.error_var.get())
        self.assertEqual(task.name, "Edited in window")


# ---------------------------------------------------------------------------
# Strict Tcl/Tk 8.6 headless harness for environments without a display
# ---------------------------------------------------------------------------


def _build_strict_tk_modules() -> dict[str, types.ModuleType]:
    """Create strict Tcl/Tk 8.6-compatible modules raising TclError on bad options."""

    class TclError(Exception):
        pass

    COMMON_WIDGET_OPTS = {
        "class_", "cursor", "style", "takefocus", "name",
        "background", "bg", "foreground", "fg", "borderwidth", "bd",
        "relief", "padx", "pady", "width", "height", "state",
        "highlightthickness", "highlightbackground", "highlightcolor",
        "font", "text", "textvariable", "anchor", "justify", "wraplength",
        "underline", "compound", "image", "padding",
    }
    PACK_OPTS = {"side", "fill", "expand", "padx", "pady", "ipadx", "ipady", "anchor", "before", "after", "in_"}
    GRID_OPTS = {"row", "column", "rowspan", "columnspan", "sticky", "padx", "pady", "ipadx", "ipady", "in_"}
    MENU_WIDGET_OPTS = {
        "activebackground", "activeborderwidth", "activeforeground", "background", "bg",
        "bd", "borderwidth", "cursor", "disabledforeground", "font", "foreground", "fg",
        "postcommand", "relief", "selectcolor", "takefocus", "tearoff", "tearoffcommand",
        "title", "type",
    }
    MENU_CASCADE_OPTS = {
        "accelerator", "activebackground", "activeforeground", "background", "bitmap",
        "columnbreak", "command", "compound", "font", "foreground", "hidemargin",
        "image", "label", "menu", "state", "underline",
    }
    MENU_COMMAND_OPTS = {
        "accelerator", "activebackground", "activeforeground", "background", "bitmap",
        "columnbreak", "command", "compound", "font", "foreground", "hidemargin",
        "image", "label", "state", "underline",
    }
    MENU_CHECK_RADIO_OPTS = MENU_COMMAND_OPTS | {
        "indicatoron", "offvalue", "onvalue", "selectcolor", "selectimage", "value", "variable",
    }

    def _check_opts(options: dict[str, object], allowed: set[str]) -> None:
        for key in options:
            if key not in allowed:
                raise TclError(f'unknown option "-{key}"')

    class Variable:
        def __init__(self, master: object = None, value: object = None, name: str | None = None) -> None:
            self._value = value
            self._traces: list[object] = []

        def set(self, value: object) -> None:
            self._value = value
            for callback in list(self._traces):
                callback("", "", "write")  # type: ignore[operator]

        def get(self) -> object:
            return self._value

        def trace_add(self, mode: str, callback: object) -> str:
            self._traces.append(callback)
            return f"trace-{len(self._traces)}"

    class StringVar(Variable):
        def __init__(self, master: object = None, value: str = "", name: str | None = None) -> None:
            super().__init__(master, str(value), name)

        def get(self) -> str:
            return str(self._value)

    class BooleanVar(Variable):
        def __init__(self, master: object = None, value: bool = False, name: str | None = None) -> None:
            super().__init__(master, bool(value), name)

        def get(self) -> bool:
            return bool(self._value)

    class Misc:
        _next_id = 1

        def __init__(self, parent: object = None, *, allowed: set[str] | None = None, **kwargs: object) -> None:
            self._id = f".w{Misc._next_id}"
            Misc._next_id += 1
            self.master = parent
            self._children: list[Misc] = []
            self._options: dict[str, object] = {}
            self._bindings: dict[str, object] = {}
            self._allowed = allowed or COMMON_WIDGET_OPTS
            self._exists = True
            self._after_seq = 0
            if isinstance(parent, Misc):
                parent._children.append(self)
            if kwargs:
                self.configure(**kwargs)

        def __str__(self) -> str:
            return self._id

        def configure(self, cnf: dict[str, object] | None = None, **kwargs: object) -> dict[str, object] | None:
            merged = dict(cnf or {}, **kwargs)
            if not merged:
                return dict(self._options)
            _check_opts(merged, self._allowed)
            self._options.update(merged)
            return None

        config = configure

        def cget(self, key: str) -> object:
            return self._options.get(key, "")

        def pack(self, **kwargs: object) -> None:
            _check_opts(kwargs, PACK_OPTS)

        def pack_forget(self) -> None:
            pass

        def grid(self, **kwargs: object) -> None:
            _check_opts(kwargs, GRID_OPTS)

        def grid_slaves(self) -> list["Misc"]:
            return list(reversed(self._children))

        def columnconfigure(self, _index: int, **_kwargs: object) -> None:
            pass

        def rowconfigure(self, _index: int, **_kwargs: object) -> None:
            pass

        def bind(self, sequence: str, func: object = None, add: object = None) -> str:
            self._bindings[sequence] = func
            return sequence

        def bind_all(self, sequence: str, func: object = None, add: object = None) -> str:
            self._bindings[sequence] = func
            return sequence

        def unbind_all(self, sequence: str) -> None:
            self._bindings.pop(sequence, None)

        def event_generate(self, sequence: str) -> None:
            handler = self._bindings.get(sequence)
            if handler is None and self.winfo_toplevel() is not self:
                handler = self.winfo_toplevel()._bindings.get(sequence)
            if callable(handler):
                handler(types.SimpleNamespace(widget=self, delta=120, x=0, y=0, x_root=0, y_root=0, width=800))

        def after(self, _ms: int, func: object = None, *args: object) -> str:
            self._after_seq += 1
            return f"after#{self._after_seq}"

        def after_idle(self, func: object, *args: object) -> str:
            self._after_seq += 1
            return f"idle#{self._after_seq}"

        def after_cancel(self, _ident: str) -> None:
            pass

        def update(self) -> None:
            pass

        def update_idletasks(self) -> None:
            pass

        def winfo_exists(self) -> bool:
            return self._exists

        def winfo_children(self) -> list["Misc"]:
            return [c for c in self._children if c._exists]

        def winfo_toplevel(self) -> "Misc":
            cur: Misc = self
            while isinstance(cur.master, Misc):
                cur = cur.master
            return cur

        def winfo_class(self) -> str:
            return type(self).__name__

        def winfo_width(self) -> int:
            return int(self._options.get("width", 640))  # type: ignore[arg-type]

        def winfo_reqwidth(self) -> int:
            return 480

        def winfo_reqheight(self) -> int:
            return 320

        def winfo_screenwidth(self) -> int:
            return 1920

        def winfo_screenheight(self) -> int:
            return 1080

        def focus_set(self) -> None:
            self.winfo_toplevel()._focused = self  # type: ignore[attr-defined]

        focus_force = focus_set

        def focus_get(self) -> object:
            return getattr(self.winfo_toplevel(), "_focused", None)

        def grab_set(self) -> None:
            pass

        def grab_release(self) -> None:
            pass

        def wait_window(self, _window: object = None) -> None:
            pass

        def clipboard_clear(self) -> None:
            self.winfo_toplevel()._clipboard = ""  # type: ignore[attr-defined]

        def clipboard_append(self, text: str) -> None:
            root = self.winfo_toplevel()
            root._clipboard = getattr(root, "_clipboard", "") + text  # type: ignore[attr-defined]

        def destroy(self) -> None:
            for child in list(self._children):
                child.destroy()
            self._exists = False

    class PhotoImage:
        def __init__(self, *, file: str | None = None, data: object = None, **_kwargs: object) -> None:
            if file is not None and not Path(file).is_file():
                raise TclError(f"couldn't open \"{file}\": no such file or directory")
            self.file = file
            self.data = data

    class Tk(Misc):
        def __init__(self, screenName: str | None = None, baseName: str | None = None, className: str = "Tk", **_kwargs: object) -> None:
            super().__init__(None, allowed=COMMON_WIDGET_OPTS | {"menu"})
            self._title = ""
            self._class_name = className
            self._icon_applied = False
            _ = (screenName, baseName)

        def iconphoto(self, _default: bool = False, *images: object) -> None:
            if images:
                self._icon_applied = True

        def iconbitmap(self, _bitmap: object = None, default: object = None) -> None:
            if _bitmap or default:
                self._icon_applied = True

        def title(self, text: str | None = None) -> str:
            if text is not None:
                self._title = text
            return self._title

        def geometry(self, _spec: str | None = None) -> str:
            return "1320x860+0+0"

        def minsize(self, _w: int, _h: int) -> None:
            pass

        def resizable(self, _w: bool, _h: bool) -> None:
            pass

        def protocol(self, _name: str, _func: object = None) -> None:
            pass

        def withdraw(self) -> None:
            pass

        def deiconify(self) -> None:
            pass

        def lift(self) -> None:
            pass

        def attributes(self, *_args: object) -> None:
            pass

        def mainloop(self) -> None:
            pass

    class Toplevel(Tk):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            Misc.__init__(self, parent, allowed=COMMON_WIDGET_OPTS | {"menu"}, **kwargs)
            self._title = ""

        def transient(self, _parent: object = None) -> None:
            pass

    class Menu(Misc):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            self._entries: list[tuple[str, dict[str, object]]] = []
            super().__init__(parent, allowed=MENU_WIDGET_OPTS, **kwargs)

        def add_command(self, **kwargs: object) -> None:
            _check_opts(kwargs, MENU_COMMAND_OPTS)
            self._entries.append(("command", dict(kwargs)))

        def add_cascade(self, **kwargs: object) -> None:
            _check_opts(kwargs, MENU_CASCADE_OPTS)
            self._entries.append(("cascade", dict(kwargs)))

        def add_radiobutton(self, **kwargs: object) -> None:
            _check_opts(kwargs, MENU_CHECK_RADIO_OPTS)
            self._entries.append(("radiobutton", dict(kwargs)))

        def add_checkbutton(self, **kwargs: object) -> None:
            _check_opts(kwargs, MENU_CHECK_RADIO_OPTS)
            self._entries.append(("checkbutton", dict(kwargs)))

        def add_separator(self) -> None:
            self._entries.append(("separator", {}))

        def entryconfigure(self, index: int, **kwargs: object) -> None:
            _check_opts(kwargs, MENU_CHECK_RADIO_OPTS | {"menu"})
            if 0 <= index < len(self._entries):
                self._entries[index][1].update(kwargs)

        def delete(self, first: int, last: int | str | None = None) -> None:
            if last == "end":
                del self._entries[first:]
            elif last is None:
                if 0 <= first < len(self._entries):
                    del self._entries[first]

        def index(self, spec: str | int) -> int | None:
            if not self._entries:
                return None
            return len(self._entries) - 1 if spec == "end" else int(spec)

        def tk_popup(self, _x: int, _y: int) -> None:
            pass

    class Text(Misc):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            self._text = ""
            self._modified = False
            super().__init__(parent, allowed=COMMON_WIDGET_OPTS | {"wrap", "insertbackground", "yscrollcommand", "xscrollcommand"}, **kwargs)

        def insert(self, index: str, chars: str, *_tags: object) -> None:
            self._text = chars if index == "1.0" and not self._text else self._text + chars

        def delete(self, _start: str, _end: str | None = None) -> None:
            self._text = ""

        def get(self, _start: str, _end: str | None = None) -> str:
            return self._text

        def see(self, _index: str) -> None:
            pass

        def yview(self, *_args: object) -> tuple[float, float]:
            return (0.0, 1.0)

        def xview(self, *_args: object) -> tuple[float, float]:
            return (0.0, 1.0)

        def tag_configure(self, _tag: str, **_kwargs: object) -> None:
            pass

        def edit_modified(self, flag: bool | None = None) -> bool:
            if flag is None:
                return self._modified
            self._modified = flag
            return flag

    class Listbox(Misc):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            self._items: list[str] = []
            self._selected: list[int] = []
            super().__init__(
                parent,
                allowed=COMMON_WIDGET_OPTS | {"exportselection", "activestyle", "selectbackground", "selectforeground", "yscrollcommand"},
                **kwargs,
            )

        def insert(self, _index: str | int, *elements: str) -> None:
            self._items.extend(str(e) for e in elements)

        def delete(self, first: int, last: int | str | None = None) -> None:
            if last == "end":
                del self._items[first:]
                self._selected = [i for i in self._selected if i < first]
            elif 0 <= first < len(self._items):
                del self._items[first]
                self._selected = []

        def selection_set(self, first: int, _last: int | None = None) -> None:
            if 0 <= first < len(self._items) and first not in self._selected:
                self._selected.append(first)

        def selection_clear(self, _first: int, _last: int | str | None = None) -> None:
            self._selected.clear()

        def curselection(self) -> tuple[int, ...]:
            return tuple(self._selected)

        def activate(self, _index: int) -> None:
            pass

        def see(self, _index: int) -> None:
            pass

        def yview(self, *_args: object) -> tuple[float, float]:
            return (0.0, 1.0)

    class Canvas(Misc):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            self._items: list[int] = []
            super().__init__(
                parent,
                allowed=COMMON_WIDGET_OPTS | {"scrollregion", "xscrollcommand", "yscrollcommand"},
                **kwargs,
            )

        def _new_item(self) -> int:
            ident = len(self._items) + 1
            self._items.append(ident)
            return ident

        def create_rectangle(self, *_coords: float, **_kwargs: object) -> int:
            return self._new_item()

        def create_line(self, *_coords: float, **_kwargs: object) -> int:
            return self._new_item()

        def create_polygon(self, *_coords: float, **_kwargs: object) -> int:
            return self._new_item()

        def create_text(self, *_coords: float, **_kwargs: object) -> int:
            return self._new_item()

        def create_window(self, *_coords: float, **_kwargs: object) -> int:
            return self._new_item()

        def itemconfigure(self, _item: int, **_kwargs: object) -> None:
            pass

        def bbox(self, _tag: str) -> tuple[int, int, int, int]:
            return (0, 0, 800, 600)

        def delete(self, _tag: str) -> None:
            self._items.clear()

        def find_all(self) -> tuple[int, ...]:
            return tuple(self._items)

        def canvasy(self, y: float) -> float:
            return float(y)

        def xview(self, *_args: object) -> tuple[float, float]:
            return (0.0, 1.0)

        def yview(self, *_args: object) -> tuple[float, float]:
            return (0.0, 1.0)

        def yview_moveto(self, _fraction: object) -> None:
            pass

        def yview_scroll(self, _number: int, _what: str) -> None:
            pass

    class Entry(Misc):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            super().__init__(parent, allowed=COMMON_WIDGET_OPTS | {"show"}, **kwargs)

        def select_range(self, _start: int, _end: int | str) -> None:
            pass

    class Button(Misc):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            super().__init__(parent, allowed=COMMON_WIDGET_OPTS | {"command"}, **kwargs)

        def invoke(self) -> object:
            cmd = self._options.get("command")
            return cmd() if callable(cmd) else None

    class Style:
        def __init__(self, _master: object = None) -> None:
            self._theme = "clam"

        def theme_use(self, name: str | None = None) -> str:
            if name is not None:
                self._theme = name
            return self._theme

        def configure(self, _style: str, **_kwargs: object) -> None:
            pass

        def map(self, _style: str, **_kwargs: object) -> None:
            pass

    class Notebook(Misc):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            self._tabs: list[Misc] = []
            self._current = 0
            super().__init__(parent, **kwargs)

        def add(self, child: Misc, **_kwargs: object) -> None:
            self._tabs.append(child)

        def tabs(self) -> tuple[str, ...]:
            return tuple(str(tab) for tab in self._tabs)

        def select(self, tab_id: int | str | None = None) -> str:
            if tab_id is None:
                return str(self._tabs[self._current]) if self._tabs else ""
            if isinstance(tab_id, int):
                self._current = tab_id
            else:
                for idx, tab in enumerate(self._tabs):
                    if str(tab) == tab_id:
                        self._current = idx
                        break
            return str(self._tabs[self._current])

        def index(self, tab_id: str) -> int:
            for idx, tab in enumerate(self._tabs):
                if str(tab) == tab_id:
                    return idx
            return 0

    class Treeview(Misc):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            self._rows: dict[str, dict[str, object]] = {}
            self._selection: tuple[str, ...] = ()
            super().__init__(
                parent,
                allowed=COMMON_WIDGET_OPTS | {"columns", "displaycolumns", "show", "selectmode", "yscrollcommand", "xscrollcommand"},
                **kwargs,
            )

        def heading(self, _col: str, **_kwargs: object) -> None:
            pass

        def column(self, _col: str, **_kwargs: object) -> None:
            pass

        def tag_configure(self, _tag: str, **_kwargs: object) -> None:
            pass

        def insert(self, parent_iid: str, _index: str | int, iid: str | None = None, **kwargs: object) -> str:
            row_id = iid or f"item-{len(self._rows) + 1}"
            entry = dict(kwargs)
            entry["_parent"] = parent_iid
            self._rows[row_id] = entry
            return row_id

        def parent(self, item: str) -> str:
            return str(self._rows.get(item, {}).get("_parent", ""))

        def item(self, item: str, option: str | None = None) -> object:
            row = self._rows.get(item, {})
            if option is None:
                return row
            return row.get(option, "")

        def delete(self, *items: str) -> None:
            for item in items:
                self._rows.pop(item, None)
            self._selection = tuple(i for i in self._selection if i in self._rows)

        def get_children(self, _item: str = "") -> tuple[str, ...]:
            return tuple(self._rows.keys())

        def exists(self, item: str) -> bool:
            return item in self._rows

        def selection(self) -> tuple[str, ...]:
            return self._selection

        def selection_set(self, *items: str) -> None:
            self._selection = tuple(items)

        def selection_remove(self, *items: str) -> None:
            self._selection = tuple(i for i in self._selection if i not in items)

        def focus(self, _item: str | None = None) -> str:
            return self._selection[0] if self._selection else ""

        def see(self, _item: str) -> None:
            pass

        def identify_row(self, _y: int) -> str:
            return next(iter(self._rows), "")

        def yview(self, *_args: object) -> tuple[float, float]:
            return (0.0, 1.0)

    class Combobox(Entry):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            Misc.__init__(self, parent, allowed=COMMON_WIDGET_OPTS | {"values", "postcommand"}, **kwargs)

    class Spinbox(Entry):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            Misc.__init__(self, parent, allowed=COMMON_WIDGET_OPTS | {"from_", "to", "increment"}, **kwargs)

    class Checkbutton(Button):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            Misc.__init__(self, parent, allowed=COMMON_WIDGET_OPTS | {"command", "variable", "onvalue", "offvalue"}, **kwargs)

    class Radiobutton(Button):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            Misc.__init__(self, parent, allowed=COMMON_WIDGET_OPTS | {"command", "variable", "value"}, **kwargs)

    class Menubutton(Button):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            Misc.__init__(self, parent, allowed=COMMON_WIDGET_OPTS | {"command", "menu", "direction"}, **kwargs)

    class Scrollbar(Misc):
        def __init__(self, parent: object = None, **kwargs: object) -> None:
            super().__init__(parent, allowed=COMMON_WIDGET_OPTS | {"orient", "command"}, **kwargs)

        def set(self, *_args: object) -> None:
            pass

    tk_mod = types.ModuleType("tkinter")
    ttk_mod = types.ModuleType("tkinter.ttk")
    filedialog_mod = types.ModuleType("tkinter.filedialog")
    messagebox_mod = types.ModuleType("tkinter.messagebox")
    simpledialog_mod = types.ModuleType("tkinter.simpledialog")
    colorchooser_mod = types.ModuleType("tkinter.colorchooser")
    scrolledtext_mod = types.ModuleType("tkinter.scrolledtext")

    tk_mod.END = "end"  # type: ignore[attr-defined]
    tk_mod.TclError = TclError  # type: ignore[attr-defined]
    tk_mod.Misc = Misc  # type: ignore[attr-defined]
    tk_mod.Event = types.SimpleNamespace  # type: ignore[attr-defined]
    tk_mod.Widget = Misc  # type: ignore[attr-defined]
    tk_mod.Tk = Tk  # type: ignore[attr-defined]
    tk_mod.PhotoImage = PhotoImage  # type: ignore[attr-defined]
    tk_mod.Toplevel = Toplevel  # type: ignore[attr-defined]
    tk_mod.Frame = Misc  # type: ignore[attr-defined]
    tk_mod.Label = Misc  # type: ignore[attr-defined]
    tk_mod.Button = Button  # type: ignore[attr-defined]
    tk_mod.Entry = Entry  # type: ignore[attr-defined]
    tk_mod.Listbox = Listbox  # type: ignore[attr-defined]
    tk_mod.Canvas = Canvas  # type: ignore[attr-defined]
    tk_mod.Text = Text  # type: ignore[attr-defined]
    tk_mod.Menu = Menu  # type: ignore[attr-defined]
    tk_mod.StringVar = StringVar  # type: ignore[attr-defined]
    tk_mod.BooleanVar = BooleanVar  # type: ignore[attr-defined]

    ttk_mod.Style = Style  # type: ignore[attr-defined]
    ttk_mod.Frame = Misc  # type: ignore[attr-defined]
    ttk_mod.Label = Misc  # type: ignore[attr-defined]
    ttk_mod.LabelFrame = Misc  # type: ignore[attr-defined]
    ttk_mod.Button = Button  # type: ignore[attr-defined]
    ttk_mod.Entry = Entry  # type: ignore[attr-defined]
    ttk_mod.Combobox = Combobox  # type: ignore[attr-defined]
    ttk_mod.Spinbox = Spinbox  # type: ignore[attr-defined]
    ttk_mod.Checkbutton = Checkbutton  # type: ignore[attr-defined]
    ttk_mod.Radiobutton = Radiobutton  # type: ignore[attr-defined]
    ttk_mod.Menubutton = Menubutton  # type: ignore[attr-defined]
    ttk_mod.Notebook = Notebook  # type: ignore[attr-defined]
    ttk_mod.Treeview = Treeview  # type: ignore[attr-defined]
    ttk_mod.Scrollbar = Scrollbar  # type: ignore[attr-defined]

    filedialog_mod.askopenfilename = lambda **_kw: ""  # type: ignore[attr-defined]
    filedialog_mod.asksaveasfilename = lambda **_kw: ""  # type: ignore[attr-defined]
    messagebox_mod.showerror = lambda *_a, **_kw: None  # type: ignore[attr-defined]
    messagebox_mod.showinfo = lambda *_a, **_kw: None  # type: ignore[attr-defined]
    messagebox_mod.showwarning = lambda *_a, **_kw: None  # type: ignore[attr-defined]
    messagebox_mod.askyesno = lambda *_a, **_kw: True  # type: ignore[attr-defined]
    messagebox_mod.askyesnocancel = lambda *_a, **_kw: False  # type: ignore[attr-defined]
    simpledialog_mod.askstring = lambda *_a, **_kw: None  # type: ignore[attr-defined]
    colorchooser_mod.askcolor = lambda *_a, **_kw: ((51, 102, 153), "#336699")  # type: ignore[attr-defined]
    scrolledtext_mod.ScrolledText = Text  # type: ignore[attr-defined]

    tk_mod.ttk = ttk_mod  # type: ignore[attr-defined]
    tk_mod.filedialog = filedialog_mod  # type: ignore[attr-defined]
    tk_mod.messagebox = messagebox_mod  # type: ignore[attr-defined]
    tk_mod.simpledialog = simpledialog_mod  # type: ignore[attr-defined]
    tk_mod.colorchooser = colorchooser_mod  # type: ignore[attr-defined]
    tk_mod.scrolledtext = scrolledtext_mod  # type: ignore[attr-defined]

    return {
        "tkinter": tk_mod,
        "tkinter.ttk": ttk_mod,
        "tkinter.filedialog": filedialog_mod,
        "tkinter.messagebox": messagebox_mod,
        "tkinter.simpledialog": simpledialog_mod,
        "tkinter.colorchooser": colorchooser_mod,
        "tkinter.scrolledtext": scrolledtext_mod,
    }


@unittest.skipIf(TK_AVAILABLE, "Real Tkinter window tests ran directly")
class HeadlessStrictTkGuiTests(unittest.TestCase):
    _saved_modules: dict[str, types.ModuleType | None] = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls._fake_tk = _build_strict_tk_modules()
        cls._saved_modules = {name: sys.modules.get(name) for name in cls._fake_tk}
        for key in list(sys.modules):
            if key == "planforge.gui" or key.startswith("planforge.gui."):
                cls._saved_modules.setdefault(key, sys.modules.pop(key))
        sys.modules.update(cls._fake_tk)

    @classmethod
    def tearDownClass(cls) -> None:
        for key in list(sys.modules):
            if key == "planforge.gui" or key.startswith("planforge.gui."):
                sys.modules.pop(key, None)
        for name, original in cls._saved_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._config_patch = patch("planforge.config.CONFIG_FILE", self.tmp / "PlanForge.conf")
        self._config_dir_patch = patch("planforge.config.CONFIG_DIR", self.tmp)
        self._recovery_dir_patch = patch("planforge.recovery.CONFIG_DIR", self.tmp)
        self._theme_dir_patch = patch("planforge.theme_library.CONFIG_DIR", self.tmp)
        self._config_patch.start()
        self._config_dir_patch.start()
        self._recovery_dir_patch.start()
        self._theme_dir_patch.start()

        from planforge.gui.app import PlanForgeApp

        self.app = PlanForgeApp()

    def tearDown(self) -> None:
        self.app.destroy()
        self._theme_dir_patch.stop()
        self._recovery_dir_patch.stop()
        self._config_dir_patch.stop()
        self._config_patch.stop()
        self._tmp.cleanup()

    def test_strict_menu_validator_rejects_postcommand_on_add_cascade(self) -> None:
        tk_mod = sys.modules["tkinter"]
        menu = tk_mod.Menu(self.app, tearoff=False)
        sub = tk_mod.Menu(menu, tearoff=False)
        with self.assertRaisesRegex(tk_mod.TclError, 'unknown option "-postcommand"'):
            menu.add_cascade(label="Broken", menu=sub, postcommand=lambda: None)

    def test_app_startup_tabs_menus_preferences_dialogs_and_pfp_save(self) -> None:
        # Both cascade submenus register postcommand on Menu, never add_cascade.
        self.assertEqual(self.app.recent_menu.cget("postcommand"), self.app._populate_recent_menu)
        self.assertEqual(self.app.layout_menu.cget("postcommand"), self.app._populate_layout_menu)
        self.assertEqual(self.app._recovery_interval_ms(), 60_000)

        # Render every tab and zoom level without errors.
        self.app.refresh_all()
        for index in range(len(self.app.notebook.tabs())):
            self.app._select_tab(index)
            self.app._on_tab_changed()
        for zoom in ("Days", "Weeks", "Months"):
            self.app.views["timeline"].zoom_var.set(zoom)
            self.app.views["timeline"].refresh()

        # Populate dynamic menus & save/autosave .pfp project files.
        self.app.session.add_task("GUI headless task")
        self.app._autosave_recovery()
        self.assertIn("snapshot updated", self.app.status_var.get())

        pfp_target = self.tmp / "saved_from_gui.pfp"
        self.assertTrue(self.app._save_to(pfp_target))
        self.assertTrue(pfp_target.is_file())
        self.app._populate_recent_menu()
        self.app._populate_layout_menu()

        # Exercise Preferences, Appearance/Theme Editor, Recovery, Import/Export & Command Palette dialogs.
        from planforge.gui.appearance import AppearanceManagerDialog, ThemeEditorDialog
        from planforge.gui.dialogs import ExportDialog, ImportDialog, TaskDialog
        from planforge.gui.preferences import PreferencesDialog
        from planforge.gui.recovery_dialog import RecoveryDialog
        from planforge.recovery import save_recovery_snapshot

        prefs = PreferencesDialog(self.app, self.app)
        prefs.interval_var.set("2 minutes")
        prefs._apply()
        self.assertEqual(self.app._recovery_interval_ms(), 120_000)
        prefs.destroy()

        appearance = AppearanceManagerDialog(self.app, self.app)
        selected_theme = appearance._selected()
        assert selected_theme is not None
        editor = ThemeEditorDialog(appearance, self.app, selected_theme)
        editor._save()
        appearance.destroy()

        record = save_recovery_snapshot(self.app.session.project, pfp_target, root=self.tmp)
        recovery_dlg = RecoveryDialog(self.app, self.app, [record])
        recovery_dlg._restore()

        task_id = self.app.session.project.tasks[0].id
        task_dlg = TaskDialog(self.app, self.app.session, task_id)
        task_dlg.name_var.set("Updated from strict GUI test")
        task_dlg.on_ok()
        self.assertTrue(task_dlg.result)

        imp_dlg = ImportDialog(self.app, self.app.session)
        imp_dlg.path_var.set(str(FIXTURES / "sample_projectlibre.xml"))
        imp_dlg._check()
        imp_dlg.on_ok()
        self.assertTrue(imp_dlg.result)

        exp_dlg = ExportDialog(self.app, self.app.session)
        exp_out = self.tmp / "exported_from_dialog.pfp"
        exp_dlg.format_var.set("PlanForge SQLite database (.pfp)")
        exp_dlg.path_var.set(str(exp_out))
        exp_dlg.on_ok()
        self.assertTrue(exp_out.is_file())

        # Convert tab wizard converting XML -> .pfp and .pfp -> .gan directly.
        convert = self.app.views["convert"]
        convert.source_mode_var.set("file")
        convert._on_source_mode_change()
        convert.source_path_var.set(str(FIXTURES / "sample_projectlibre.xml"))
        convert._inspect()
        converted_pfp = self.tmp / "converted_wizard.pfp"
        convert.dest_format_var.set("PlanForge SQLite database (.pfp)")
        convert.dest_path_var.set(str(converted_pfp))
        convert._convert()
        self.assertTrue(converted_pfp.is_file())

        convert.source_path_var.set(str(converted_pfp))
        convert._inspect()
        converted_gan = self.tmp / "converted_wizard.gan"
        convert._pick_format("ganttproject")
        convert.dest_path_var.set(str(converted_gan))
        convert._convert()
        self.assertTrue(converted_gan.is_file())

        self.assertTrue(self.app._icon_applied)
        self.assertEqual(self.app._class_name, "PlanForge")
        self.app.show_command_palette()

    def test_start_date_changes_persist_across_settings_tab_switches_task_dialog_and_save(self) -> None:
        from datetime import date
        from planforge.gui.dialogs import TaskDialog

        settings = self.app.views["settings"]
        self.app.select_tab_by_key("settings")
        self.app._on_tab_changed()

        # 1. Explicit Apply in Settings to a date earlier than today (2026-10-23)
        settings.start_var.set("2026-09-01")
        self.assertTrue(settings._apply())
        self.assertEqual(self.app.session.project.start_date, date(2026, 9, 1))
        self.assertEqual(settings.start_var.get(), "2026-09-01")
        self.assertEqual(self.app.session.project.tasks[0].start_date, date(2026, 9, 1))

        # 2. Type UK-formatted start date and switch tabs WITHOUT clicking Apply Changes
        settings.start_var.set("14/09/2026")
        self.app.select_tab_by_key("tasks")
        self.app._on_tab_changed()
        self.assertEqual(self.app.session.project.start_date, date(2026, 9, 14))
        self.app.select_tab_by_key("settings")
        self.app._on_tab_changed()
        self.assertEqual(settings.start_var.get(), "2026-09-14")

        # 3. Type start date in Settings and save directly via save_project()
        pfp_file = self.tmp / "saved_after_settings_edit.pfp"
        self.app._save_to(pfp_file)
        settings.start_var.set("2026-10-05")
        self.assertTrue(self.app.save_project())
        self.assertEqual(self.app.session.project.start_date, date(2026, 10, 5))

        # 4. Edit start date directly inside TaskDialog (Edit Task)
        first_task = self.app.session.project.tasks[0]
        dlg = TaskDialog(self.app, self.app.session, first_task.id)
        dlg.start_date_var.set("2026-08-17")
        dlg.on_ok()
        self.assertTrue(dlg.result, dlg.error_var.get())
        self.assertEqual(first_task.start_date, date(2026, 8, 17))
        self.assertEqual(self.app.session.project.start_date, date(2026, 8, 17))


    def test_people_and_materials_sheet_hierarchy_and_task_material_dialog(self) -> None:
        from planforge.gui.dialogs import ResourceDialog, TaskDialog

        # Add a top-level Materials group and nested Dell PowerEdge server via ResourceDialog
        hdr_dlg = ResourceDialog(self.app, self.app.session, default_type="material")
        hdr_dlg.name_var.set("Materials")
        hdr_dlg.rate_var.set("0")
        hdr_dlg.on_ok()
        self.assertTrue(hdr_dlg.result, hdr_dlg.error_var.get())

        srv_dlg = ResourceDialog(self.app, self.app.session, default_type="material")
        srv_dlg.name_var.set("Dell PowerEdge server")
        srv_dlg.material_label_var.set("unit")
        srv_dlg.rate_var.set("5000")
        srv_dlg.parent_var.set("Materials")
        srv_dlg.on_ok()
        self.assertTrue(srv_dlg.result, srv_dlg.error_var.get())

        cable_dlg = ResourceDialog(self.app, self.app.session, default_type="material")
        cable_dlg.name_var.set("cat6 network cabling")
        cable_dlg.material_label_var.set("metre")
        cable_dlg.rate_var.set("6.49")
        cable_dlg.parent_var.set("Materials")
        cable_dlg.on_ok()
        self.assertTrue(cable_dlg.result, cable_dlg.error_var.get())

        # Assign both materials with quantities inside TaskDialog on the first task
        first_task = self.app.session.project.tasks[0]
        tdlg = TaskDialog(self.app, self.app.session, first_task.id)
        tdlg.mat_choice_var.set("Dell PowerEdge server")
        tdlg.mat_qty_var.set("1")
        tdlg._add_selected_material()
        tdlg.mat_choice_var.set("cat6 network cabling")
        tdlg.mat_qty_var.set("50")
        tdlg._add_selected_material()
        tdlg.on_ok()
        self.assertTrue(tdlg.result, tdlg.error_var.get())
        self.app.refresh_all()

        # Verify People & Materials tree structure, blank Max. Units on materials, and Costs/Tasks tabs
        people_view = self.app.views["people"]
        mat_hdr = next(r for r in self.app.session.project.resources if r.name == "Materials")
        srv = next(r for r in self.app.session.project.resources if r.name == "Dell PowerEdge server")
        self.assertEqual(people_view.tree.parent(srv.id), mat_hdr.id)
        srv_vals = people_view.tree.item(srv.id, "values")
        self.assertEqual(srv_vals[1], "Material")
        self.assertEqual(srv_vals[2], "unit")
        self.assertEqual(srv_vals[4], "")  # Max. Units blank on Material rows just like ProjectLibre!

        costs_view = self.app.views["costs"]
        self.assertIn("5,324.50", costs_view.cards["Material cost"].get())


if __name__ == "__main__":
    unittest.main()
