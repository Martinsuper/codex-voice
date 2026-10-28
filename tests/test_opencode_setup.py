import json
from pathlib import Path
import re
import tempfile
import unittest
from opencode_setup import (CONFIG_KEYS, MARKER, PLUGIN_DIR_REL, PLUGIN_REL,
                            backup, entries, merge_global_jsonc, plugin_uri,
                            render_plugin, same_file, update_config,
                            update_global, write_json)


class UpdateConfigTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.plugin = self.folder / "app" / "tui.js"
        self.plugin.parent.mkdir(parents=True)
        self.plugin.write_text("// plugin")
        self.uri = self.plugin.resolve().as_uri()
    def config(self, name, data):
        path = self.folder / name
        path.write_text(json.dumps(data))
        return path
    def update(self, name, key, remove):
        path = self.folder / name
        data = update_config(path, key, self.plugin, remove=remove)
        if data is not None:
            write_json(path, data)
        return path
    def test_install_registers_plugin_and_keeps_other_keys(self):
        path = self.config("cli.json", {"$schema": "https://example/v2/cli.json", "plugins": ["file:///other/plugin.js"]})
        self.update("cli.json", "plugins", remove=False)
        saved = json.loads(path.read_text())
        self.assertEqual(saved["$schema"], "https://example/v2/cli.json")
        self.assertEqual(saved["plugins"], ["file:///other/plugin.js", self.uri])
    def test_repeated_install_is_a_no_op_that_returns_none(self):
        path = self.config("cli.json", {"plugins": [self.uri]})
        self.assertIsNone(update_config(path, "plugins", self.plugin, remove=False))
        self.assertEqual(json.loads(path.read_text()), {"plugins": [self.uri]})
    def test_install_into_missing_file_creates_only_needed_key(self):
        path = self.update("cli.json", "plugins", remove=False)
        self.assertEqual(json.loads(path.read_text()), {"plugins": [self.uri]})
    def test_remove_keeps_unrelated_entries(self):
        path = self.config("cli.json", {"plugins": [self.uri, "file:///other/plugin.js"]})
        self.update("cli.json", "plugins", remove=True)
        self.assertEqual(json.loads(path.read_text()), {"plugins": ["file:///other/plugin.js"]})
    def test_remove_from_missing_file_is_a_no_op(self):
        self.assertIsNone(update_config(self.folder / "cli.json", "plugins", self.plugin, remove=True))
    def test_same_file_matches_uri_forms_and_rejects_others(self):
        self.assertTrue(same_file(self.uri, self.plugin))
        self.assertFalse(same_file("file:///elsewhere/tui.js", self.plugin))
        self.assertFalse(same_file("relative/path.js", self.plugin))
    def test_entries_rejects_non_string_lists(self):
        with self.assertRaises(ValueError):
            entries({"plugins": [1, 2]}, "plugins")
        self.assertEqual(entries({}, "plugin"), [])
        self.assertEqual(entries({"plugin": None}, "plugin"), [])


class GlobalRegistrationTests(unittest.TestCase):
    """The global opencode.json(c) plugins array — server-side registration."""
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.config_dir = self.folder / "opencode"
        self.plugin_dir = self.config_dir / PLUGIN_DIR_REL
        self.plugin_dir.mkdir(parents=True)
        (self.plugin_dir / "tui.js").write_text(f"// {MARKER}")
        self.state_dir = self.folder / "state"
        self.uri = plugin_uri(self.config_dir)
    def path(self):
        return self.config_dir / "opencode.json"
    def merge(self, raw, remove=False):
        return merge_global_jsonc(raw, self.uri, remove=remove)
    def update(self, initial=None, remove=False):
        if initial is not None:
            self.path().write_text(initial)
        return update_global(self.config_dir, self.state_dir, remove=remove)
    def test_missing_file_is_created_with_only_the_plugin(self):
        report = self.update()
        self.assertTrue(report["registered"])
        self.assertEqual(json.loads(self.path().read_text()), {"plugins": [self.uri]})
    def test_plain_json_keeps_other_keys_and_backs_up(self):
        report = self.update(json.dumps({"model": "x/big", "plugins": ["file:///a.js"]}))
        self.assertTrue(report["registered"])
        self.assertTrue(Path(report["backup"]).is_file())
        saved = json.loads(self.path().read_text())
        self.assertEqual(saved["model"], "x/big")
        self.assertEqual(saved["plugins"], ["file:///a.js", self.uri])
    def test_plain_json_install_is_idempotent_without_new_backup(self):
        self.update()
        first = self.path().read_text()
        report = self.update()
        self.assertTrue(report["registered"])
        self.assertNotIn("backup", report)
        self.assertEqual(self.path().read_text(), first)
    def test_remove_keeps_others_and_reports_unregistered(self):
        self.update(json.dumps({"plugins": [self.uri, "file:///a.js"]}))
        report = self.update(remove=True)
        self.assertFalse(report["registered"])
        self.assertEqual(json.loads(self.path().read_text())["plugins"], ["file:///a.js"])
    def test_jsonc_array_keeps_comments_and_entries(self):
        raw = ('{\n  // user comment\n  "model": "x", // trailing\n'
               '  "plugins": [\n    "file:///a.js"\n  ]\n}')
        text, changed = self.merge(raw)
        self.assertTrue(changed)
        self.assertIn("user comment", text)
        self.assertIn("// trailing", text)
        self.assertIn(self.uri, text)
        self.assertIn('"file:///a.js"', text)
    def test_jsonc_empty_array_filled_inline(self):
        text, changed = self.merge('{"plugins": []}')
        self.assertEqual(text, '{"plugins": ["%s"]}' % self.uri.replace('"', '\\"'))
        self.assertTrue(changed)
    def test_jsonc_without_plugins_key_inserts_after_first_brace(self):
        text, changed = self.merge('{"model": "x"}')
        self.assertEqual(text, '{"plugins": ["%s"],"model": "x"}' % self.uri.replace('"', '\\"'))
    def test_jsonc_remove_strips_only_our_entry(self):
        raw = '{\n  "plugins": [\n    "file:///a.js", // keep1\n    "%s", // ours\n    "file:///b.js"\n  ]\n}' % self.uri
        text, changed = self.merge(raw, remove=True)
        self.assertTrue(changed)
        self.assertNotIn(self.uri, text)
        self.assertIn('"file:///a.js"', text)
        self.assertIn('"file:///b.js"', text)
        self.assertIn("// keep1", text)
        self.assertNotIn("// ours", text)
    def test_repository_style_openbreed_jsonc_roundtrip(self):
        raw = ('{\n  "$schema": "https://opencode.ai/config.json",\n'
               '  "theme": "dark"\n}')
        report = self.update(raw)
        self.assertTrue(report["registered"])
        saved = json.loads(self.path().read_text())
        self.assertEqual(saved["theme"], "dark")
        self.assertEqual(saved["plugins"], [self.uri])
    def test_ambiguous_jsonc_reports_manual_hint_and_touches_nothing(self):
        before = '{ // one\n  "plugins": ["file:///a.js"],\n  // two\n  "sub": {"plugins": []}\n}'
        report = self.update(before)
        self.assertFalse(report["registered"])
        self.assertIn("手工", report["error"])
        self.assertEqual(self.path().read_text(), before)
    def test_non_array_plugins_reports_manual_hint(self):
        before = '{"plugins": "wrong"}'
        report = self.update(before)
        self.assertFalse(report["registered"])
        self.assertIn("手工", report["error"])
        self.assertEqual(self.path().read_text(), before)
    def test_directory_uri_matches_entry_point_slash_forms(self):
        # The global array stores the directory; slash variants must compare
        # equal, while file parts inside it must not.
        self.assertTrue(same_file(self.uri, self.plugin_dir))
        self.assertTrue(same_file(self.uri + "/", self.plugin_dir))
        self.assertFalse(same_file(self.uri + "/index.js", self.plugin_dir))


class SetupScriptTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.config_dir = self.folder / "opencode"
        self.state_dir = self.folder / "state"
        self.source = self.folder / "template.js"
        self.source.write_text('const MARKER = "codex-voice-opencode-v1"\nconst STATE_DIR = __CODEX_VOICE_STATE_DIR__\nexport default {}\n')
    def run_setup(self, mode, **overrides):
        import subprocess, sys
        script = Path(__file__).resolve().parent.parent / "src" / "opencode_setup.py"
        command = [sys.executable, str(script), "--" + mode, "--config-dir", str(self.config_dir), "--state-dir", str(self.state_dir), "--plugin-source", str(self.source)]
        for key, value in overrides.items():
            command += ["--" + key.replace("_", "-"), str(value)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)
    def plugin_path(self):
        return self.config_dir / PLUGIN_REL
    def plugin_directory(self):
        return self.config_dir / PLUGIN_DIR_REL
    def test_status_reports_unconfigured_before_install(self):
        status = self.run_setup("status")
        self.assertFalse(status["configured"])
        self.assertFalse(status["opencodeFound"])
    def test_install_renders_state_dir_and_registers(self):
        result = self.run_setup("install")
        self.assertTrue(result["configured"])
        content = self.plugin_path().read_text()
        self.assertIn(MARKER, content)
        self.assertNotIn("__CODEX_VOICE_STATE_DIR__", content)
        self.assertIn(json.dumps(str(self.state_dir)), content)
        for name, key in CONFIG_KEYS:
            if name == "tui.json" and not (self.config_dir / name).exists():
                continue
            self.assertIn(self.plugin_path().resolve().as_uri(), json.loads((self.config_dir / name).read_text())[key])
        self.assertTrue(result["backups"] == [])
    def test_reinstall_never_corrupts_existing_config(self):
        self.run_setup("install")
        before = {name: (self.config_dir / name).read_text() for name, _ in CONFIG_KEYS if (self.config_dir / name).exists()}
        result = self.run_setup("install")
        self.assertTrue(result["configured"])
        for name, content in before.items():
            self.assertEqual((self.config_dir / name).read_text(), content)
        for name, _ in CONFIG_KEYS:
            path = self.config_dir / name
            if path.exists():
                self.assertIsInstance(json.loads(path.read_text()), dict, f"{name} must stay a JSON object")
    def test_install_backs_up_existing_config(self):
        self.config_dir.mkdir(parents=True)
        (self.config_dir / "cli.json").write_text(json.dumps({"plugins": ["file:///keep.js"]}))
        result = self.run_setup("install")
        self.assertEqual(len(result["backups"]), 1)
        backup = Path(result["backups"][0])
        self.assertEqual(json.loads(backup.read_text()), {"plugins": ["file:///keep.js"]})
        self.assertEqual(json.loads((self.config_dir / "cli.json").read_text())["plugins"], ["file:///keep.js", self.plugin_path().resolve().as_uri()])
    def test_remove_deregisters_and_deletes_plugin(self):
        self.run_setup("install")
        result = self.run_setup("remove")
        self.assertTrue(result["removed"])
        self.assertFalse(self.plugin_path().exists())
        status = self.run_setup("status")
        self.assertFalse(status["configured"])
        # Unrelated plugins survive removal.
        self.assertEqual(json.loads((self.config_dir / "cli.json").read_text())["plugins"], [])
    def test_render_plugin_requires_placeholder(self):
        broken = self.folder / "broken.js"
        broken.write_text("export default {}")
        with self.assertRaises(ValueError):
            render_plugin(broken, self.state_dir)
    def test_backup_survives_missing_source(self):
        self.assertIsNone(backup(self.folder / "missing.json", self.state_dir))
    # --- server part (index.js) and global registration, script level -----
    def server_path(self):
        return self.plugin_directory() / "index.js"
    def test_install_writes_index_js_server_part(self):
        result = self.run_setup("install")
        self.assertTrue(result["configured"])
        self.assertTrue(result["globalRegistered"])
        self.assertEqual(result["globalPluginsFile"], str(self.config_dir / "opencode.json"))
        server = self.server_path().read_text()
        self.assertIn(MARKER, server)
        self.assertIn(json.dumps(str(self.state_dir)), server)
        self.assertEqual(json.loads((self.config_dir / "opencode.json").read_text())["plugins"], [plugin_uri(self.config_dir)])
    def test_reinstall_keeps_global_file_and_index_js_untouched(self):
        self.run_setup("install")
        before = self.server_path().read_text()
        global_before = (self.config_dir / "opencode.json").read_text()
        result = self.run_setup("install")
        self.assertTrue(result["configured"])
        self.assertEqual(self.server_path().read_text(), before)
        self.assertEqual((self.config_dir / "opencode.json").read_text(), global_before)
        self.assertEqual(result["backups"], [])
    def test_install_respects_manual_server_part(self):
        self.plugin_directory().mkdir(parents=True)
        (self.plugin_directory() / "server.js").write_text("// mine")
        self.run_setup("install")
        self.assertEqual((self.plugin_directory() / "server.js").read_text(), "// mine")
        self.assertFalse(self.server_path().exists())
    def test_fallback_server_symlink_counts_and_is_cleaned_on_remove(self):
        # Simulate a machine configured by the old fallback script
        # (server.js → tui.js, no index.js).
        self.run_setup("install")
        self.server_path().unlink()
        (self.plugin_directory() / "server.js").symlink_to(self.plugin_path().name)
        status = self.run_setup("status")
        self.assertTrue(status["configured"])
        self.assertEqual(status["serverPart"], str(self.plugin_directory() / "server.js"))
        self.run_setup("remove")
        self.assertFalse(self.plugin_directory().exists())
    def test_remove_deletes_server_part_and_global_entry(self):
        (self.config_dir).mkdir(parents=True)
        (self.config_dir / "opencode.json").write_text(json.dumps({"model": "keep"}))
        self.run_setup("install")
        result = self.run_setup("remove")
        self.assertTrue(result["removed"])
        self.assertFalse(self.server_path().exists())
        self.assertFalse(self.plugin_path().exists())
        saved = json.loads((self.config_dir / "opencode.json").read_text())
        self.assertEqual(saved, {"model": "keep", "plugins": []})
        self.assertFalse(plugin_uri(self.config_dir) in json.dumps(saved))
    def test_status_reports_full_configuration(self):
        self.run_setup("install")
        status = self.run_setup("status")
        self.assertTrue(status["configured"])
        self.assertTrue(status["globalRegistered"])
        self.assertEqual(status["serverPart"], str(self.server_path()))
        # status is read-only: repeated calls change nothing.
        again = self.run_setup("status")
        self.assertEqual(again["configured"], status["configured"])
    def test_install_on_ambiguous_jsonc_reports_manual_hint(self):
        self.config_dir.mkdir(parents=True)
        ambiguous = ('{ // one\n  "plugins": ["file:///a.js"],\n'
                     '  // two\n  "sub": {"plugins": []}\n}')
        (self.config_dir / "opencode.json").write_text(ambiguous)
        result = self.run_setup("install")
        self.assertFalse(result["configured"])
        self.assertFalse(result["globalRegistered"])
        self.assertIn("手工", result["globalError"])
        # Untouched user file, everything else still installed.
        self.assertEqual((self.config_dir / "opencode.json").read_text(), ambiguous)
        self.assertTrue(self.server_path().is_file())
        cli = json.loads((self.config_dir / "cli.json").read_text())
        self.assertIn(self.plugin_path().resolve().as_uri(), cli["plugins"])


if __name__ == "__main__":
    unittest.main()
