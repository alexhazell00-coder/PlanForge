# Quality-of-life features

## Themes and appearance

Open **View → Manage Themes…** to browse built-in and locally installed themes. Search and filter the library, apply a theme, duplicate a built-in or installed theme for customization, preview palette changes, and import/export portable JSON packages. Built-ins are protected, package data is size-limited and validated, and packages cannot run code. The theme library is offline-first and never contacts a catalogue server. Removing the active custom theme switches to Light.

The built-in themes are Light, Dark, Midnight, High Contrast and Classic. Use the toolbar theme control or **Ctrl+T** to cycle them. A specific built-in theme or **System Default** is available under **View → Theme**. System Default makes a best-effort offline light/dark check using the OS appearance preference (Windows registry, macOS appearance setting, or Linux desktop/environment hints); if unavailable it safely falls back to Light. Custom themes are applied from the library. macOS uses Command-modified shortcuts.

## Commands, project history and recovery

Open **Tools → Command Palette…** or press **Ctrl+Shift+P**. Filter available commands, move with Up/Down, press Enter to run, or Escape to close. Typing a name never invokes it automatically.

**File → Open Recent** lists up to ten locally remembered project paths. The history can be cleared from its submenu; missing paths are shown disabled. Opening or saving a project adds it to the history.

Project edits can be undone and redone from **Edit** or the keyboard, with up to 100 complete project snapshots. Undo and redo operate on project data and do not intercept native text-entry editing. Save state is tracked so undoing past a saved version correctly marks the project unsaved.

Crash recovery is enabled by default and stores atomic, separate SQLite snapshots in the per-user PlanForge settings directory. On startup, available recovery copies can be restored or discarded. Restoring does not overwrite the original `.pfp`; save explicitly to preserve recovered changes. The snapshot interval and enable/disable control are in **Tools → Preferences…**. Recovery files for a project are removed after a successful save or explicit discard.

## Workspace and keyboard preferences

**Tools → Preferences…** keeps application preferences separate from project settings. It controls Overview suggestions, default Gantt zoom, displayed date format (ISO, UK, US or long), recovery autosave interval, and customizable New/Open/Save/Undo/Redo key letters. The modifier remains Ctrl on Windows/Linux and Command on macOS; configured keys must be unique and cannot conflict with built-in shortcuts.

The Tasks toolbar's **Columns** menu toggles Duration, Start, Finish, Done, Predecessor, Person and Cost. Visibility persists locally. **View → Workspace Layouts** saves and applies named layouts containing the active tab, Gantt zoom and task-column visibility; saved layouts can be removed from the same menu.

Task and Gantt rows offer context menus with relevant actions. Overview suggestions are based on the current project's task, resource, assignment, dependency and dirty state; individual suggestions can be dismissed and the panel can be hidden.

Preferences live in the per-user PlanForge settings directory: `%APPDATA%/PlanForge` on Windows, `~/Library/Application Support/PlanForge` on macOS, or `$XDG_CONFIG_HOME/PlanForge` (default `~/.config/PlanForge`) on Linux. Custom theme JSON files are in its `themes` subdirectory. The INI settings are versioned, atomically written, and compatible with earlier `PlanForge.conf` files. Invalid values are ignored or replaced with safe defaults; malformed settings are preserved as a `.corrupt` backup when settings are next written.

## Validation and platform notes

These features keep project files, import/export formats, scheduling and Function Point Calculator behavior separate from application preferences. Theme packages and settings are treated as data, not executable code. Automated tests cover session undo/redo, preference validation and persistence, theme packages, recovery snapshots, project import/export and other workflows.

The application uses Tkinter's cross-platform widgets and palette rather than attempting to infer a system-wide light/dark preference, which is not exposed consistently by Tkinter. This environment does not provide Tkinter, so GUI tests are skipped here and interactive appearance/behavior has not been visually verified on Windows or macOS. The core data and configuration tests run headlessly.
