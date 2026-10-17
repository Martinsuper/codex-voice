import copy
import json
from pathlib import Path
import plistlib
import shlex
import tempfile
import unittest
from hook_setup import EVENTS, MARKER, configured, count_hooks, owned, update_hooks


class HookSetupTests(unittest.TestCase):
    def test_preserves_unrelated_handlers_and_metadata(self):
        data={'description':'existing','hooks':{'PreToolUse':[{'matcher':'Other','hooks':[{'type':'command','command':'other-observer'}]}]}}
        result=update_hooks(copy.deepcopy(data),'/Applications/Codex Voice.app')
        self.assertEqual(result['description'],'existing')
        self.assertEqual(result['hooks']['PreToolUse'][0],data['hooks']['PreToolUse'][0])
        self.assertTrue(configured(result));self.assertEqual(count_hooks(result),5)
    def test_quoted_app_path_and_idempotent_install(self):
        result=update_hooks({},'/Applications/Codex Voice.app')
        command=result['hooks']['Interrupt'][0]['hooks'][0]['command']
        self.assertEqual(shlex.split(command)[0],'/Applications/Codex Voice.app/Contents/MacOS/CodexVoice')
        before=json.dumps(result,sort_keys=True)
        update_hooks(result,'/Applications/Codex Voice.app')
        self.assertEqual(json.dumps(result,sort_keys=True),before)
    def test_remove_only_owned_hooks(self):
        result=update_hooks({'hooks':{'Stop':[{'hooks':[{'command':'unrelated-stop'}]}]}},'/Applications/Codex Voice.app')
        update_hooks(result,'/Applications/Codex Voice.app',remove=True)
        self.assertEqual(result,{'hooks':{'Stop':[{'hooks':[{'command':'unrelated-stop'}]}]}})
    def test_marker_in_an_unrelated_command_is_not_ownership(self):
        self.assertFalse(owned('echo --hook --observer-id '+MARKER))
        self.assertFalse(owned('/Applications/CodexVoice.app/Contents/MacOS/CodexVoice --hook --observer-id wrong'))
    def test_all_distinct_events_are_required(self):
        result=update_hooks({},'/Applications/Codex Voice.app')
        result['hooks']['PreToolUse']*=5
        del result['hooks']['PermissionRequest']
        self.assertFalse(configured(result))
    def test_legacy_hook_is_migrated_without_dropping_other_code(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle=Path(folder)/'Legacy.app';resources=bundle/'Contents/Resources';resources.mkdir(parents=True)
            (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'local.rico.CodexVoice'}))
            command=shlex.join(['python3',str(resources/'voice_bridge.py'),'--state-dir',folder,'hook'])
            data={'hooks':{'Interrupt':[{'hooks':[{'command':command},{'command':'other-command'}]}]}}
            result=update_hooks(data,'/Applications/Codex Voice.app')
            self.assertEqual(result['hooks']['Interrupt'][0]['hooks'],[{'command':'other-command'}])
            self.assertEqual(count_hooks(result),5)


if __name__=='__main__':unittest.main()
