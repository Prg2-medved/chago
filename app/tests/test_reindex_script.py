"""Linux host lifecycle tests. Windows skips are not acceptance evidence."""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import pytest


linux_only = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux Bash/flock/signals required")
ROOT = Path(__file__).resolve().parents[2]

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json,os,sys,time
from pathlib import Path
root=Path(os.environ['FAKE_ROOT'])
args=sys.argv[1:]
with (root/'calls').open('a') as f:
    f.write(json.dumps(args)+'\n')
scenario=os.environ.get('SCENARIO','success')
statefile=root/'container.json'
appfile=root/'app.json'
def load():
    return json.loads(statefile.read_text()) if statefile.exists() else None
def save(state):
    statefile.write_text(json.dumps(state))
def load_app():
    return json.loads(appfile.read_text()) if appfile.exists() else None
def save_app(state):
    appfile.write_text(json.dumps(state))
def resolve(target):
    for state in (load(), load_app()):
        if state and target in (state['id'], state['name'], '/'+state['name']):
            return state
    return None
if args[0]=='compose':
    args=args[5:]
    if args[:2]==['config','--format']:
        print(json.dumps({'name':'test-project'}))
    elif args[0]=='stop':
        if scenario=='stop-failure': sys.exit(1)
        state=load_app()
        if state:
            state['status']='exited'
            save_app(state)
    elif args[0]=='run':
        if scenario=='launch-failure': sys.exit(1)
        if scenario=='creation-delay':
            (root/'launching').touch()
            time.sleep(.6)
        state={'id':'a'*64,'name':args[args.index('--name')+1],
               'label':args[args.index('--label')+1].split('=',1)[1],
               'project':'test-project','status':'exited','code':7 if scenario in ('build-failure','both-failure') else 0}
        if scenario in ('inference','creation-delay','lost-id','kill-required','docker-unavailable','foreign'):
            state['status']='running'
        if scenario=='foreign': state['label']='foreign-run'
        save(state)
        if scenario=='lost-id': sys.exit(1)
        print(state['id'])
    elif args[0]=='up':
        if scenario in ('up-failure','both-failure'): sys.exit(1)
        status='exited' if scenario=='app-exit' else 'restarting' if scenario=='app-restarting' else 'running'
        save_app({'id':'app-a','name':'app','project':'test-project',
                  'status':status,'code':0,'restart_count':0})
    elif args[0]=='ps':
        counter=root/'ps-count'
        count=int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(count+1))
        state=load_app()
        if state:
            if scenario=='changed-id' and count>0:
                state['id']='app-b'
                save_app(state)
            print(state['id'])
    else: sys.exit(2)
elif args[0]=='inspect':
    state=resolve(args[-1])
    if not state: sys.exit(1)
    if scenario=='docker-unavailable' and (root/'allow-failure').exists(): sys.exit(1)
    if '--format' not in args: print('{}'); sys.exit(0)
    fmt=args[args.index('--format')+1]
    if '.Config.Labels' in fmt:
        print('|'.join([state['id'],'/'+state['name'],state.get('label',''),state['project']]))
    elif '.RestartCount' in fmt:
        print(state['status']+'|'+str(state.get('restart_count',0)))
    else:
        print(state['status']+'|'+str(state['code']))
elif args[:2]==['container','ls']:
    state=load()
    if scenario=='docker-unavailable': sys.exit(1)
    if state: print(state['name'])
elif args[0]=='exec':
    state=load_app()
    if not state or args[1]!=state['id'] or state['status']!='running': sys.exit(1)
    counter=root/'probe-count'
    count=int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(count+1))
    if scenario=='probe-delay' and count<1: sys.exit(1)
    if scenario in ('http-timeout','bad-json'): sys.exit(1)
elif args[0]=='stop':
    state=load()
    if not state or args[-1] not in (state['id'],state['name']): sys.exit(1)
    if scenario!='kill-required': state['status']='exited'; state['code']=143; save(state)
elif args[0]=='kill':
    state=load()
    if not state or args[-1] not in (state['id'],state['name']): sys.exit(1)
    state['status']='exited'; state['code']=137; save(state)
elif args[0]=='rm':
    state=load()
    if not state or args[-1] not in (state['id'],state['name']): sys.exit(1)
    assert state['status']=='exited'
    (root/'removed').write_text(json.dumps(state))
    statefile.unlink()
else: sys.exit(2)
'''


@pytest.fixture
def host(tmp_path):
    for command in ("bash", "flock", "timeout", "python3"):
        if shutil.which(command) is None:
            pytest.fail(f"Linux prerequisite missing: {command}")
    (tmp_path / "data").mkdir()
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    script = tmp_path / "reindex.sh"
    # Keep production at 60 seconds. Shorten only copied failure fixtures.
    script.write_text((ROOT / "reindex.sh").read_text().replace("SECONDS + 60", "SECONDS + 5"))
    script.chmod(0o755)
    executable = tmp_path / "docker"
    executable.write_text(FAKE_DOCKER)
    executable.chmod(0o755)
    return tmp_path, {**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
                      "FAKE_ROOT": str(tmp_path)}


def calls(root):
    return [json.loads(line) for line in (root / "calls").read_text().splitlines()]


def run(host, scenario):
    root, env = host
    return subprocess.run(["bash", str(root / "reindex.sh")], cwd="/", env={**env, "SCENARIO": scenario},
                          capture_output=True, text=True, timeout=20)


@linux_only
@pytest.mark.parametrize("scenario,status", [
    ("success", 0), ("build-failure", 7), ("both-failure", 7), ("up-failure", 1),
    ("app-exit", 1), ("app-restarting", 1), ("http-timeout", 1), ("bad-json", 1),
    ("probe-delay", 0), ("changed-id", 0), ("stop-failure", 1), ("foreign", 1), ("lost-id", 143),
    ("launch-failure", 1),
])
def test_lifecycle_and_recovery(host, scenario, status):
    result = run(host, scenario)
    assert result.returncode == status, result.stderr
    root, _ = host
    history = calls(root)
    commands = [row[5] for row in history if row[0] == "compose"]
    assert commands[0:2] == ["config", "stop"]
    assert all(row[-1] == "app" for row in history if row[0] == "compose" and row[5] in ("up", "stop"))
    if scenario == "stop-failure":
        assert "run" not in commands
    elif scenario == "foreign":
        assert "up" not in commands
        assert not any(row[0] in ("stop", "kill", "rm") for row in history)
    else:
        assert commands.index("stop") < commands.index("run") < commands.index("up")
        if scenario != "launch-failure":
            assert (root / "removed").exists()
    if scenario in ("success", "probe-delay", "changed-id", "build-failure"):
        assert "HTTP health verified" in result.stdout


def wait_for(root, predicate, process):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if predicate():
            return
        assert process.poll() is None
        time.sleep(.02)
    pytest.fail("fake Docker synchronization timed out")


@linux_only
@pytest.mark.parametrize("scenario", ["inference", "creation-delay", "kill-required", "docker-unavailable"])
@pytest.mark.parametrize("sig,status", [(signal.SIGINT, 130), (signal.SIGTERM, 143)])
def test_signal_terminates_only_owned_container(host, scenario, sig, status):
    root, env = host
    process = subprocess.Popen(["bash", str(root / "reindex.sh")], env={**env, "SCENARIO": scenario},
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        marker = root / ("launching" if scenario == "creation-delay" else "container.json")
        wait_for(root, marker.exists, process)
        if scenario == "docker-unavailable":
            # Let launch reconciliation finish before making Docker inaccessible.
            time.sleep(.3)
            (root / "allow-failure").touch()
        process.send_signal(sig)
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == status, stdout + stderr
        history = calls(root)
        assert not any(row[0] == "compose" and row[5] == "up" for row in history)
        if scenario == "docker-unavailable":
            assert "termination unconfirmed" in stderr
            assert not (root / "removed").exists()
        else:
            assert (root / "removed").exists()
            assert all(row[-1] == "a" * 64 for row in history if row[0] in ("stop", "kill", "rm"))
            if scenario == "kill-required":
                assert any(row[0] == "kill" for row in history)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


@linux_only
def test_second_operation_rejected_before_docker(host):
    root, env = host
    process = subprocess.Popen(["bash", str(root / "reindex.sh")], env={**env, "SCENARIO": "inference"},
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        wait_for(root, (root / "container.json").exists, process)
        before = len(calls(root))
        result = run(host, "success")
        assert result.returncode == 1 and "operation busy" in result.stderr
        # The first process may inspect; a second config/stop must never occur.
        assert not any(row[0] == "compose" for row in calls(root)[before:])
    finally:
        process.terminate()
        process.communicate(timeout=20)


@linux_only
def test_bash_syntax():
    result = subprocess.run(["bash", "-n", str(ROOT / "reindex.sh")], capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("scenario,exit_code", [
    ("success", 0), ("build-failure", 7), ("probe-delay", 0), ("changed-id", 0),
])
def test_fake_app_survives_one_shot_removal(tmp_path, scenario, exit_code):
    executable = tmp_path / "fake_docker.py"
    executable.write_text(FAKE_DOCKER)
    env = {**os.environ, "FAKE_ROOT": str(tmp_path), "SCENARIO": scenario}

    def docker(*args, expected=0):
        result = subprocess.run([sys.executable, str(executable), *args], env=env,
                                capture_output=True, text=True, timeout=5)
        assert result.returncode == expected, result.stderr
        return result.stdout.strip()

    def compose(*args):
        return docker("compose", "--project-directory", str(tmp_path), "-f", "compose.yaml", *args)

    one_shot = compose("run", "--detach", "--name", "test-indexer", "--label", "chago.reindex-run=test-run", "app")
    assert docker("inspect", "--format", "{{.State.Status}}|{{.State.ExitCode}}", one_shot) == f"exited|{exit_code}"
    compose("up", "-d", "--no-deps", "app")
    app_before = (tmp_path / "app.json").read_bytes()
    docker("rm", one_shot)
    assert not (tmp_path / "container.json").exists()
    assert (tmp_path / "app.json").read_bytes() == app_before
    docker("inspect", one_shot, expected=1)
    docker("inspect", "test-indexer", expected=1)
    docker("inspect", "unknown-container", expected=1)
    app_id = compose("ps", "-q", "app")
    assert app_id == "app-a"
    assert docker("inspect", "--format", "{{.State.Status}}|{{.RestartCount}}", app_id) == "running|0"
    docker("exec", app_id, "python", "-c", "probe", expected=1 if scenario == "probe-delay" else 0)
    if scenario == "probe-delay":
        docker("exec", app_id, "python", "-c", "probe")
    current_id = compose("ps", "-q", "app")
    assert current_id == ("app-b" if scenario == "changed-id" else "app-a")
    assert docker("inspect", "--format", "{{.State.Status}}|{{.RestartCount}}", current_id) == "running|0"
    if scenario == "changed-id":
        docker("inspect", app_id, expected=1)
        docker("exec", app_id, "python", "-c", "probe", expected=1)
