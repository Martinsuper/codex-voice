#!/usr/bin/env python3
"""Check a moved app with a clean environment and a temporary user profile."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import select
import subprocess
import tempfile
import time


def run(arguments, environment, **kwargs):
    result = subprocess.run([str(arg) for arg in arguments], env=environment, capture_output=True, text=True, timeout=30, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr[-5000:] or result.stdout[-5000:])
    return result.stdout


def verify_speech_preferences(python, resources, profile, codex, environment):
    settings_path = profile / 'settings.json'
    settings_path.write_text(json.dumps({'enabled': False, 'other': 'keep'}))
    expected = {'voice': 'Tingting', 'rate': 225, 'address': 'Rico', 'intervals': [7, 11, 19]}
    for restarted in (False, True):
        process = subprocess.Popen([str(python), str(resources / 'voice_engine.py'), '--state-dir', str(profile), '--codex-dir', str(codex)],
                                   env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pending = b''

        def snapshot():
            nonlocal pending
            deadline = time.monotonic() + 15
            while True:
                if b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    return json.loads(line)
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                    raise RuntimeError('Timed out waiting for bundled voice engine')
                chunk = os.read(process.stdout.fileno(), 131072)
                if not chunk:
                    raise RuntimeError('Bundled voice engine stopped before reporting its preferences')
                pending += chunk

        try:
            first = snapshot()
            expected_version = (Path(__file__).resolve().parent.parent / 'VERSION').read_text().strip()
            assert first['version'] == expected_version
            assert first['enabled'] is False
            if restarted:
                assert all(first['speech'][key] == value for key, value in expected.items()), first['speech']
                assert first['pause']['minutes'] == 37
                assert first['usageAnnouncement']['enabled'] is False
                assert first['usageLowAnnouncement']['enabled'] is False and first['usageLowAnnouncement']['threshold'] == 25
                assert first['reminderRules']['result']['max_plays'] == 1
                assert first['reminderRules']['approval']['intervals'] == [7,11,19]
                assert first['quietHours']['enabled'] is True and first['quietHours']['days'] == [0,1,2,3,4]
            else:
                assert first['speech']['rate'] == 185 and first['speech']['address'] == '老板'
                assert first['pause']['minutes'] == 15
                assert first['usageAnnouncement']['enabled'] is True
                assert first['usageLowAnnouncement']['enabled'] is True and first['usageLowAnnouncement']['threshold'] == 20
                assert first['reminderRules']['result']['max_plays'] == 0 and first['quietHours']['enabled'] is False
                process.stdin.write((json.dumps({'action': 'set_speech_settings', 'settings': expected}) + '\n').encode())
                process.stdin.flush()
                updated = snapshot()
                assert all(updated['speech'][key] == value for key, value in expected.items()), updated['speech']
                saved = json.loads(settings_path.read_text())
                assert saved['speech'] == expected and saved['other'] == 'keep' and saved['enabled'] is False
                process.stdin.write(b'{"action":"set_speech_settings","settings":{"rate":0}}\n')
                process.stdin.flush()
                invalid = snapshot()
                assert invalid['speech']['settingsError'] and json.loads(settings_path.read_text()) == saved
                process.stdin.write(b'{"action":"set_pause_duration","minutes":37}\n')
                process.stdin.flush()
                paused = snapshot()
                assert paused['pause']['minutes'] == 37 and paused['mutedUntil'] == 0
                saved = json.loads(settings_path.read_text())
                assert saved['pause_minutes'] == 37 and saved['other'] == 'keep' and saved['enabled'] is False
                process.stdin.write(b'{"action":"set_pause_duration","minutes":0}\n')
                process.stdin.flush()
                invalid_pause = snapshot()
                assert invalid_pause['pause']['error'] and json.loads(settings_path.read_text()) == saved
                process.stdin.write(b'{"action":"set_usage_reset_enabled","enabled":false}\n')
                process.stdin.flush()
                announcement = snapshot()
                assert announcement['usageAnnouncement']['enabled'] is False
                saved = json.loads(settings_path.read_text())
                assert saved['usage_reset_announcement'] is False and saved['other'] == 'keep' and saved['speech'] == expected
                process.stdin.write(b'{"action":"set_usage_reset_enabled","enabled":"false"}\n')
                process.stdin.flush()
                invalid_announcement = snapshot()
                assert invalid_announcement['usageAnnouncement']['error'] and json.loads(settings_path.read_text()) == saved
                process.stdin.write(b'{"action":"set_usage_low_settings","settings":{"enabled":false,"threshold":25}}\n')
                process.stdin.flush()
                low = snapshot()['usageLowAnnouncement']
                assert low['enabled'] is False and low['threshold'] == 25
                saved = json.loads(settings_path.read_text())
                assert saved['usage_low_announcement'] is False and saved['usage_low_threshold'] == 25 and saved['other'] == 'keep'
                assert saved['speech'] == expected and saved['pause_minutes'] == 37 and saved['usage_reset_announcement'] is False
                process.stdin.write(b'{"action":"set_usage_low_settings","settings":{"threshold":0}}\n')
                process.stdin.flush()
                invalid_low = snapshot()
                assert invalid_low['usageLowAnnouncement']['error'] and json.loads(settings_path.read_text()) == saved
                process.stdin.write(b'{"action":"set_reminder_rules","rules":{"result":{"max_plays":1},"approval":{"intervals":[7,11,19]}}}\n')
                process.stdin.flush()
                rules = snapshot()
                assert rules['reminderRules']['result']['max_plays'] == 1 and rules['reminderRules']['approval']['intervals'] == [7,11,19]
                saved = json.loads(settings_path.read_text())
                process.stdin.write(b'{"action":"set_reminder_rules","rules":{"result":{"max_plays":-1}}}\n')
                process.stdin.flush()
                assert snapshot()['rulesError'] and json.loads(settings_path.read_text()) == saved
                process.stdin.write(b'{"action":"set_quiet_hours","settings":{"enabled":true,"start":"23:00","end":"09:00","days":[0,1,2,3,4],"allow_approval":true}}\n')
                process.stdin.flush()
                quiet = snapshot()
                assert quiet['quietHours']['enabled'] is True and quiet['quietHours']['allow_approval'] is True
                saved = json.loads(settings_path.read_text())
                process.stdin.write(b'{"action":"set_quiet_hours","settings":{"start":"24:00"}}\n')
                process.stdin.flush()
                assert snapshot()['quietHours']['error'] and json.loads(settings_path.read_text()) == saved
                assert saved['other'] == 'keep' and saved['speech'] == expected and saved['usage_low_threshold'] == 25
        finally:
            if process.poll() is None:
                process.stdin.write(b'{"action":"quit"}\n')
                process.stdin.flush()
            try:
                _, errors = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise
            assert process.returncode == 0, errors.decode(errors='replace')[-3000:]


def main():
    parser = argparse.ArgumentParser();parser.add_argument("app",type=Path);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="codex-voice-relocation-") as temporary:
        base=Path(temporary);moved=base/"A folder with spaces"/args.app.name
        moved.parent.mkdir();shutil.copytree(args.app,moved,symlinks=True)
        runtime=base/"profile";codex=base/"codex-profile";codex.mkdir()
        environment={key:value for key,value in os.environ.items() if not key.startswith("PYTHON") and key not in ["__PYVENV_LAUNCHER__","CODEX_HOME"]}
        environment.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin")
        executable=moved/"Contents/MacOS/CodexVoice"
        bundle_info = plistlib.loads((moved/'Contents/Info.plist').read_bytes())
        expected_version = (Path(__file__).resolve().parent.parent/'VERSION').read_text().strip()
        assert bundle_info['CodexVoiceVersion'] == expected_version
        assert bundle_info['CFBundleShortVersionString'] == expected_version.split('-')[0]
        info=json.loads(run([executable,"--runtime-info","--state-dir",runtime],environment))
        assert info['pythonVersion']=='3.14.8',info
        assert Path(info['executable']).resolve().is_relative_to(moved.resolve())
        assert Path(info['prefix']).resolve().is_relative_to(moved.resolve())
        assert all(not value or Path(value).resolve().is_relative_to(moved.resolve()) for value in info['path']),info['path']
        assert str(moved/'Contents/Resources') in info['path'], 'App runtime must include its trusted companion-module directory'
        run(['/usr/bin/codesign','--verify','--deep','--strict',moved],environment)
        for path in [executable,moved/'Contents/Resources/AudioDeviceInfo']:
            assert set(run(['/usr/bin/lipo','-archs',path],environment).split())=={'arm64','x86_64'}
        setup=moved/'Contents/Resources/hook_setup.py'
        python=moved/'Contents/Frameworks/Python.framework/Versions/3.14/bin/python3.14'
        child=dict(environment,PYTHONHOME=str(python.parent.parent),PYTHONPATH=str(moved/'Contents/Resources'),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONSAFEPATH='1',PYTHONUTF8='1')
        result=json.loads(run([python,setup,'--install','--app',moved,'--codex-dir',codex,'--state-dir',runtime],child))
        assert result['configured'] and result['needsReview'] and result['count']==5
        assert not (codex/'config.toml').exists(),"Hook setup must not write trust or approval settings"
        payload=json.dumps({'hook_event_name':'PreToolUse','session_id':'packaging-test','tool_name':'request_user_input','tool_use_id':'test-question','cwd':str(base)})
        run([executable,'--hook','--state-dir',runtime],environment,input=payload)
        events=list((runtime/'inbox').glob('*.json'));assert len(events)==1
        event=json.loads(events[0].read_text());assert event['event']['tool_name']=='request_user_input'
        opencode_setup=moved/'Contents/Resources/opencode_setup.py'
        assert opencode_setup.is_file() and (moved/'Contents/Resources/opencode_plugin.js').is_file(),'OpenCode companion scripts must ship in Resources'
        opencode_config=base/'opencode-profile'
        result=json.loads(run([python,opencode_setup,'--install','--config-dir',opencode_config,'--state-dir',runtime,'--plugin-source',moved/'Contents/Resources/opencode_plugin.js'],child))
        assert result['configured'] and result['globalRegistered'],result
        rendered=(opencode_config/'plugins/codex-voice/tui.js').read_text()
        assert '__CODEX_VOICE_STATE_DIR__' not in rendered and 'codex-voice-opencode-v1' in rendered
        server=(opencode_config/'plugins/codex-voice/index.js').read_text()
        assert 'codex-voice-opencode-v1' in server and '__CODEX_VOICE_STATE_DIR__' not in server,'Server part must be rendered too'
        opencode_global=opencode_config/'opencode.json'
        global_plugins=json.loads(opencode_global.read_text())['plugins']
        plugin_dir_uri=(opencode_config/'plugins/codex-voice').resolve().as_uri()
        assert plugin_dir_uri in global_plugins,f'Global plugins must register the plugin directory: {global_plugins}'
        reinstall=json.loads(run([python,opencode_setup,'--install','--config-dir',opencode_config,'--state-dir',runtime,'--plugin-source',moved/'Contents/Resources/opencode_plugin.js'],child))
        assert reinstall['configured'] and json.loads(opencode_global.read_text())['plugins']==global_plugins,'Reinstall must keep the global plugins array unchanged'
        assert json.loads((opencode_config/'cli.json').read_text()),'Reinstall must keep cli.json a valid object'
        removed=json.loads(run([python,opencode_setup,'--remove','--config-dir',opencode_config,'--state-dir',runtime,'--plugin-source',moved/'Contents/Resources/opencode_plugin.js'],child))
        assert removed['removed'] and not removed['globalRegistered']
        assert plugin_dir_uri not in json.dumps(json.loads(opencode_global.read_text())),'Remove must deregister the plugin directory'
        assert not (opencode_config/'plugins/codex-voice').exists(),'Remove must delete the plugin files'
        verify_speech_preferences(python, moved/'Contents/Resources', runtime, codex, child)
        print(json.dumps({'relocation':True,'cleanPath':True,'embeddedPython':info['pythonVersion'],'universalBinaries':True,'deepSignatureValid':True,'isolatedHookInstall':True,'hookTrustUnchanged':True,'bundledHookEntry':True,'opencodeInstallIdempotent':True,'speechPreferencesPersistAndRestart':True,'invalidSpeechSettingsRejected':True,'pauseDurationPersistsAndRestarts':True,'invalidPauseDurationRejected':True,'usageResetPreferencePersistsAndRestarts':True,'invalidUsageResetSettingRejected':True,'lowUsagePreferencesPersistAndRestart':True,'invalidLowUsageThresholdRejected':True,'reminderRulesPersistAndRestart':True,'quietHoursPersistAndRestart':True}))


if __name__=='__main__':main()
