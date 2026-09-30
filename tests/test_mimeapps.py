"""Headless tests for desktop_entry_editor.mimeapps (needs only PyGObject/Gio).

Run from the project root:  python3 -m unittest tests.test_mimeapps -v
Uses a throw-away XDG home so it never touches your real mimeapps.list.
"""
import os
import sys
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="dee-test-")
os.environ["XDG_DATA_HOME"] = os.path.join(_TMP, "data")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_TMP, "config")
os.makedirs(os.environ["XDG_CONFIG_HOME"])
_APPS = os.path.join(os.environ["XDG_DATA_HOME"], "applications")
os.makedirs(_APPS)
for _n, _mt in (("fakeone", "application/x-xz-compressed-tar"),
                ("faketwo", "application/x-xz-compressed-tar")):
    with open(os.path.join(_APPS, f"{_n}.desktop"), "w") as f:
        f.write(f"[Desktop Entry]\nType=Application\nName={_n}\nExec=true %f\nMimeType={_mt};\n")

# Gio finds handlers through mimeinfo.cache (normally written by
# update-desktop-database), so write one by hand for determinism.
with open(os.path.join(_APPS, "mimeinfo.cache"), "w") as f:
    f.write("[MIME Cache]\napplication/x-xz-compressed-tar=fakeone.desktop;faketwo.desktop;\n")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gi.repository import Gio  # noqa: E402
from desktop_entry_editor import mimeapps as m  # noqa: E402

TARXZ = "application/x-xz-compressed-tar"


class SuffixTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(m.normalize_suffix("*.TAR.XZ"), "tar.xz")
        self.assertEqual(m.normalize_suffix(" .exe "), "exe")

    def test_multi_part_suffix(self):
        self.assertEqual(m.mime_for_suffix(".tar.xz"), TARXZ)

    def test_exe_resolves(self):
        self.assertIsNotNone(m.mime_for_suffix("exe"))

    def test_unknown_suffix(self):
        self.assertIsNone(m.mime_for_suffix("zzqqxx"))

    def test_index_parses_and_skips_non_suffix_globs(self):
        p = os.path.join(_TMP, "globs2")
        with open(p, "w") as f:
            f.write("# c\n50:text/x-makefile:Makefile\n50:a/b:*.tar.xz\n"
                    "50:a/b:*.txz\n50:c/d:README*\n50:c/d:*.a[b]\n")
        self.assertEqual(m.load_suffix_index([p]), {"a/b": ["tar.xz", "txz"]})

    def test_system_index_has_tar_xz(self):
        self.assertIn("tar.xz", m.load_suffix_index().get(TARXZ, []))


    def test_disambiguate_keeps_only_the_real_owner(self):
        raw = {"text/html": ["html", "htm"],
               "application/xhtml+xml": ["html", "xhtml"],
               "application/vnd.efi.iso": ["iso"],
               "application/x-wii-rom": ["iso", "wbfs"]}
        out = m.disambiguate_suffixes(raw)
        self.assertEqual(out["text/html"], ["html", "htm"])
        self.assertEqual(out["application/xhtml+xml"], ["xhtml"])
        self.assertEqual(out["application/x-wii-rom"], ["wbfs"])
        self.assertEqual(out["application/vnd.efi.iso"], ["iso"])

    def test_disambiguate_on_real_database_has_no_shared_suffix(self):
        out = m.disambiguate_suffixes(m.load_suffix_index())
        seen = {}
        for mime, sfx in out.items():
            for s in sfx:
                self.assertNotIn(s, seen, f"{s}: {seen.get(s)} vs {mime}")
                seen[s] = mime
        self.assertIn("tar.xz", out.get(TARXZ, []))

    def test_new_categories_present(self):
        self.assertIsNotNone(m.category_by_key("torrent"))
        self.assertIsNotNone(m.category_by_key("contacts"))


class DefaultTests(unittest.TestCase):
    def test_candidates_include_fakes(self):
        ids = [m.app_id(a) for a in m.candidates_for(TARXZ)]
        self.assertIn("fakeone.desktop", ids)
        self.assertIn("faketwo.desktop", ids)

    def test_set_and_reset_default(self):
        one = next(a for a in m.candidates_for(TARXZ) if m.app_id(a) == "fakeone.desktop")
        self.assertEqual(m.set_default(one, [TARXZ]), [])
        self.assertEqual(m.app_id(m.get_default(TARXZ)), "fakeone.desktop")
        self.assertIn(TARXZ, m.user_customized_types())
        m.reset_defaults([TARXZ])
        self.assertNotIn(TARXZ, m.user_customized_types())

    def test_category_state_and_categories_are_sane(self):
        keys = [c.key for c in m.CATEGORIES]
        self.assertEqual(len(keys), len(set(keys)))
        for c in m.CATEGORIES:
            m.category_state(c)
            m.category_candidates(c)


if __name__ == "__main__":
    unittest.main()
