"""Docker Desktop boundary contracts; no running business containers required."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location(
    "desktop_stack", Path(__file__).resolve().parents[1] / "scripts/desktop-stack.py"
)
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


def test_desktop_mounts_keep_daemon_paths_and_do_not_forward_shell_secrets():
    workspace = Path("/Users/operator/Work Space/icp_diag")
    image = "sha256:" + "a" * 64
    command = desktop.tool_command(workspace, image, ["python3", "example.py"])
    assert command[:4] == ["docker", "--context", "desktop-linux", "run"]
    assert f"type=bind,src={workspace},dst={workspace}" in command
    assert "type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock" in command
    assert command[-3:] == [image, "python3", "example.py"]
    assert "--network=none" in command and "--pull=never" in command
    assert "--env" not in command and "--env-file" not in command
    with pytest.raises(ValueError, match="immutable"):
        desktop.tool_command(workspace, "floating:tag", [])


def test_native_license_volume_requires_this_project_and_exact_daemon_path():
    name = "icp-diag-local-license"
    mountpoint = "/var/lib/docker/volumes/" + name + "/_data"
    config = {"DESKTOP_LICENSE_VOLUME": name, "LICENSE_ROOT": mountpoint}
    record = {"Name": name, "Mountpoint": mountpoint, "Driver": "local", "Options": None}
    mount = desktop.license_volume_mount(config, record, "icp-diag-local")
    command = desktop.tool_command(Path("/workspace"), "sha256:" + "a" * 64, ["python3"], mount)
    assert "type=volume,src=" + name + ",dst=" + mountpoint in command
    for values, volume, project in (
        (config, record, "icp-diag-another"),
        ({**config, "LICENSE_ROOT": "/workspace/runtime/license"}, record, "icp-diag-local"),
        (config, {**record, "Options": {"device": "/other-host-path"}}, "icp-diag-local"),
    ):
        with pytest.raises(ValueError, match="exact Mountpoint"):
            desktop.license_volume_mount(values, volume, project)


def test_desktop_rejects_linux_before_contacting_docker():
    with patch.object(desktop.sys, "platform", "linux"), \
         patch.object(desktop.sys, "argv", ["desktop-stack.py", "compose", "ps"]), \
         patch.object(desktop.subprocess, "check_output") as inspect:
        with pytest.raises(ValueError, match="macOS"):
            desktop.main()
        inspect.assert_not_called()


def test_native_mac_writer_blocks_license_initialization_before_docker():
    with patch.object(desktop.sys, "platform", "darwin"), \
         patch.object(desktop.sys, "argv", ["desktop-stack.py", "license-init"]), \
         patch.object(desktop.socket, "socket") as socket, \
         patch.object(desktop.subprocess, "check_output") as inspect:
        socket.return_value.__enter__.return_value.connect_ex.return_value = 0
        with pytest.raises(ValueError, match="native Mac service"):
            desktop.main()
        inspect.assert_not_called()


def test_desktop_delegates_to_existing_stack_with_complete_runtime_env():
    image = "sha256:" + "b" * 64
    with patch.object(desktop.sys, "platform", "darwin"), \
         patch.object(desktop.sys, "argv", ["desktop-stack.py", "compose", "ps"]), \
         patch.object(desktop.subprocess, "check_output", return_value=json.dumps([
             {"Os": "linux", "Id": image}])) as inspect, \
         patch.object(desktop.customer_bundle, "read_env", return_value={}), \
         patch.object(desktop.subprocess, "run") as run:
        desktop.main()
    assert inspect.call_args.args[0][:4] == ["docker", "--context", "desktop-linux", "image"]
    command = run.call_args.args[0]
    assert command[-8:] == ["python3", str(desktop.WORKSPACE / "deployment/scripts/local-stack.py"),
                            "--project", "icp-diag-local", "--env-file",
                            str(desktop.WORKSPACE / "runtime/config/docker.env"), "compose", "ps"]
    assert run.call_args.kwargs == {"check": True}
