import json
from pathlib import Path
import tempfile
import unittest
from opencode_setup import CONFIG_KEYS, MARKER, PLUGIN_REL, backup, entries, render_plugin, same_file, update_config, write_json


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


if __name__ == "__main__":
    unittest.main()
