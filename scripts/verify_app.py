#!/usr/bin/env python3
"""Check a moved app with a clean environment and a temporary user profile."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def run(arguments, environment, **kwargs):
    result = subprocess.run([str(arg) for arg in arguments], env=environment, capture_output=True, text=True, timeout=30, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr[-5000:] or result.stdout[-5000:])
    return result.stdout


def main():
    parser = argparse.ArgumentParser();parser.add_argument("app",type=Path);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="codex-voice-relocation-") as temporary:
        base=Path(temporary);moved=base/"A folder with spaces"/args.app.name
        moved.parent.mkdir();shutil.copytree(args.app,moved,symlinks=True)
        runtime=base/"profile";codex=base/"codex-profile";codex.mkdir()
        environment={key:value for key,value in os.environ.items() if not key.startswith("PYTHON") and key not in ["__PYVENV_LAUNCHER__","CODEX_HOME"]}
        environment.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin",CODEX_HOME=str(codex))
        executable=moved/"Contents/MacOS/CodexVoice"
        info=json.loads(run([executable,"--runtime-info","--state-dir",runtime],environment))
        assert info['pythonVersion']=='3.14.8',info
        assert Path(info['executable']).resolve().is_relative_to(moved.resolve())
        assert Path(info['prefix']).resolve().is_relative_to(moved.resolve())
        assert all(not value or Path(value).resolve().is_relative_to(moved.resolve()) for value in info['path']),info['path']
        run(['/usr/bin/codesign','--verify','--deep','--strict',moved],environment)
        for path in [executable,moved/'Contents/Resources/AudioDeviceInfo']:
            assert set(run(['/usr/bin/lipo','-archs',path],environment).split())=={'arm64','x86_64'}
        setup=moved/'Contents/Resources/hook_setup.py'
        python=moved/'Contents/Frameworks/Python.framework/Versions/3.14/bin/python3.14'
        child=dict(environment,PYTHONHOME=str(python.parent.parent),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
        result=json.loads(run([python,setup,'--install','--app',moved,'--codex-dir',codex,'--state-dir',runtime],child))
        assert result['configured'] and result['needsReview'] and result['count']==5
        assert not (codex/'config.toml').exists(),"Hook setup must not write trust or approval settings"
        payload=json.dumps({'hook_event_name':'PreToolUse','session_id':'packaging-test','tool_name':'request_user_input','tool_use_id':'test-question','cwd':str(base)})
        run([executable,'--hook','--state-dir',runtime],environment,input=payload)
        events=list((runtime/'inbox').glob('*.json'));assert len(events)==1
        event=json.loads(events[0].read_text());assert event['event']['tool_name']=='request_user_input'
        print(json.dumps({'relocation':True,'cleanPath':True,'embeddedPython':info['pythonVersion'],'universalBinaries':True,'deepSignatureValid':True,'isolatedHookInstall':True,'hookTrustUnchanged':True,'bundledHookEntry':True}))


if __name__=='__main__':main()
