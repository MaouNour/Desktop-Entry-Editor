# Working notes: MIME / default-apps merge

## Original request (kept verbatim in spirit)
- Editor is tested on Fedora 44, GNOME 50.
- Add default apps (mail, browser, ...) with the ability to change them.
- Same by file suffix (exe, tar.xz, ...).
- Isolate work into tasks and send the edited files after each task.
- Merge the feature files into the app, check they work as described, improve
  them without burning all the tokens, and keep prompts/thoughts in a text file.

## What I found
- The feature zip only overlapped the app in browser.py (added tabs); the rest
  were new files. Merging = copy files + add tests/__init__.py.
- 63 suffixes are claimed by more than one MIME type (.iso by 7, .py by 2,
  .html by 2), so changing the "wrong" row would look like it did nothing.

## Tasks (files sent after each)
1. Merge: feature files + browser.py into the app; 9 backend tests pass.
2. Backend/UI data: disambiguate_suffixes() so each suffix lists only the type
   the system resolves it to; added Contacts and Torrents categories; +3 tests.
3. file_types.py: Escape closes the app chooser dialog.
4. window.py: "Set as Default…" button in the editor's MIME Types section.
5. README + this file + full package archive.

## Verified vs not verified
- Verified here: everything compiles; 12 headless tests pass (backend, Gio only,
  throwaway config dir, never touches the real mimeapps.list).
- NOT verified: any GTK4/libadwaita UI. The sandbox has no GTK, so the tabs,
  dialogs and the new editor button are untested. Run on Fedora 44 and send
  the terminal output if anything breaks.

## Ideas not done
- Editable suffix-to-MIME override (user MIME XML), terminal choice
  (not a MIME association), Gtk.ListView for the file-type list if the
  ~800 rows ever feel heavy.
