"""The deployment scripts in infra/scripts behave the same on Windows and Linux.

These are the parts that can be checked without any AWS or Atlas resource:
how arguments for the AWS CLI are built, what happens to the temporary file
that carries a secret, and what the preflight check reads from the settings
file.
"""

import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
import types

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "infra" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import common  # noqa: E402
import manage_secrets  # noqa: E402
import preflight  # noqa: E402

SECRET = "s3cr3t-value-that-must-never-leak"


# ------------------------------------------------------------------------------
# The file:// argument of the AWS CLI
# ------------------------------------------------------------------------------


def test_the_file_argument_for_a_windows_path_is_the_plain_path_after_the_prefix():
    path = PureWindowsPath(r"C:\Users\hp\AppData\Local\Temp\antiproxy-abcd\request.json")
    argument = common.cli_file_argument(path)

    assert argument == r"file://C:\Users\hp\AppData\Local\Temp\antiproxy-abcd\request.json"
    # What the AWS CLI opens is everything after "file://": it must be a real
    # Windows path, starting with the drive letter.
    opened = argument[len("file://"):]
    assert opened == str(path)
    assert PureWindowsPath(opened).drive == "C:"
    # The form that broke: a file URL, which leaves "/C:/..." after the prefix.
    assert argument != path.as_uri()
    assert not opened.startswith("/")


def test_the_file_argument_for_a_linux_path():
    path = PurePosixPath("/tmp/antiproxy-abcd/request.json")
    argument = common.cli_file_argument(path)
    assert argument == "file:///tmp/antiproxy-abcd/request.json"
    assert argument[len("file://"):] == str(path)


def test_a_windows_path_with_spaces_is_kept_as_it_is():
    path = PureWindowsPath(r"C:\Users\First Last\AppData\Local\Temp\antiproxy-x\request.json")
    assert common.cli_file_argument(path)[len("file://"):] == str(path)


# ------------------------------------------------------------------------------
# Storing a secret: off the command line, and the file is always removed
# ------------------------------------------------------------------------------


class RecordingAws:
    """Stands in for the AWS CLI: records the call and what the request file held."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.arguments: list[str] = []
        self.request: dict = {}
        self.request_path: Path | None = None

    def __call__(self, *args: str, region: str | None = None, check: bool = True):
        self.arguments = list(args)
        argument = args[args.index("--cli-input-json") + 1]
        assert argument.startswith("file://")
        self.request_path = Path(argument[len("file://"):])
        self.request = json.loads(self.request_path.read_text(encoding="utf-8"))
        if self.fail:
            raise SystemExit(1)
        return types.SimpleNamespace(returncode=0, stdout="{}", stderr="")


def test_a_secret_reaches_the_cli_through_a_file_and_never_through_the_command_line(monkeypatch):
    recorder = RecordingAws()
    monkeypatch.setattr(manage_secrets, "aws", recorder)

    manage_secrets.Store("ap-south-1", "/antiproxy/prod").put("JWT_SECRET_KEY", SECRET)

    assert all(SECRET not in part for part in recorder.arguments)
    assert recorder.request == {
        "Name": "/antiproxy/prod/JWT_SECRET_KEY",
        "Value": SECRET,
        "Type": "SecureString",
        "Overwrite": True,
        "Tier": "Standard",
    }
    # The path handed to the CLI was a real, openable path on this system.
    assert recorder.request_path is not None and recorder.request_path.is_absolute()
    assert not recorder.request_path.exists()
    assert not recorder.request_path.parent.exists()


def test_the_temporary_file_is_removed_when_the_aws_call_fails(monkeypatch):
    recorder = RecordingAws(fail=True)
    monkeypatch.setattr(manage_secrets, "aws", recorder)

    with pytest.raises(SystemExit):
        manage_secrets.Store("ap-south-1", "/antiproxy/prod").put("JWT_SECRET_KEY", SECRET)

    assert recorder.request["Value"] == SECRET  # the call was reached
    assert not recorder.request_path.exists()
    assert not recorder.request_path.parent.exists()


def test_the_temporary_file_is_removed_when_the_call_is_interrupted(monkeypatch):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    created: list[str] = []
    real_mkdtemp = manage_secrets.tempfile.mkdtemp

    def recording_mkdtemp(*args, **kwargs):
        created.append(real_mkdtemp(*args, **kwargs))
        return created[-1]

    monkeypatch.setattr(manage_secrets, "aws", interrupted)
    monkeypatch.setattr(manage_secrets.tempfile, "mkdtemp", recording_mkdtemp)

    with pytest.raises(KeyboardInterrupt):
        manage_secrets.Store("ap-south-1", "/antiproxy/prod").put("JWT_SECRET_KEY", SECRET)
    assert created and not Path(created[0]).exists()


def test_nothing_secret_is_printed_when_a_value_is_stored(monkeypatch, capsys):
    monkeypatch.setattr(manage_secrets, "aws", RecordingAws())
    manage_secrets.Store("ap-south-1", "/antiproxy/prod").put("JWT_SECRET_KEY", SECRET)
    printed = capsys.readouterr()
    assert SECRET not in printed.out + printed.err
    assert "stored JWT_SECRET_KEY" in printed.out


# ------------------------------------------------------------------------------
# init before the database exists
# ------------------------------------------------------------------------------


class MemoryStore:
    def __init__(self, existing: dict[str, str] | None = None) -> None:
        self.path = "/antiproxy/prod"
        self.region = "ap-south-1"
        self.values = dict(existing or {})

    def names(self) -> dict[str, str]:
        return {name: "2026-10-11T10:00:00" for name in self.values}

    def put(self, name: str, value: str) -> None:
        self.values[name] = value


def test_init_before_the_database_exists_stores_everything_else_and_says_what_is_next(monkeypatch, capsys):
    answers = iter(["d" * 36, "long-enough-password", "long-enough-password"])
    monkeypatch.setattr(manage_secrets.getpass, "getpass", lambda prompt="": next(answers))
    monkeypatch.setattr("builtins.input", lambda prompt="": "admin@example.org")
    store = MemoryStore()

    assert manage_secrets.command_init(store, out={}, only_if_missing=False) == 0

    assert set(store.values) == {
        "JWT_SECRET_KEY", "VISION_SERVICE_API_KEY", "RECOGNITION_SIGNING_KEY",
        "DUCKDNS_TOKEN", "BOOTSTRAP_ADMIN_EMAIL", "BOOTSTRAP_ADMIN_PASSWORD",
    }
    assert len({store.values[name] for name in manage_secrets.GENERATED}) == 3
    printed = capsys.readouterr().out
    assert "MONGODB_URL: later" in printed and "tf.py up" in printed
    for value in store.values.values():
        if value != "admin@example.org":
            assert value not in printed


def test_the_later_run_from_tf_up_adds_only_the_database_address_and_asks_nothing(monkeypatch):
    def no_prompt(*args, **kwargs):
        raise AssertionError("nothing may be asked at this point")

    monkeypatch.setattr(manage_secrets.getpass, "getpass", no_prompt)
    monkeypatch.setattr("builtins.input", no_prompt)
    monkeypatch.setattr(manage_secrets, "create_database_user", lambda project_id: "p@ss/w:rd")
    # The first administrator has signed in and the bootstrap values were removed.
    store = MemoryStore({name: "x" for name in [*manage_secrets.GENERATED, "DUCKDNS_TOKEN"]})
    out = {"atlas_project_id": "0123456789abcdef01234567", "atlas_srv_address": "mongodb+srv://c.ab1cd.mongodb.net"}

    assert manage_secrets.command_init(store, out, only_if_missing=True) == 0

    url = store.values["MONGODB_URL"]
    assert url.startswith("mongodb+srv://antiproxy_app:p%40ss%2Fw%3Ard@c.ab1cd.mongodb.net/anti_proxy_attendance?")
    assert "BOOTSTRAP_ADMIN_EMAIL" not in store.values


# ------------------------------------------------------------------------------
# Running commands: a missing program is an explanation, not a stack trace
# ------------------------------------------------------------------------------


def test_a_program_that_is_not_installed_gives_a_plain_message(capsys):
    with pytest.raises(SystemExit):
        common.run(["this-program-does-not-exist-anywhere", "--version"], capture=True)
    assert "is not installed or not on PATH" in capsys.readouterr().err


def test_child_processes_never_use_a_pager():
    assert common.child_environment()["AWS_PAGER"] == ""


# ------------------------------------------------------------------------------
# Preflight: reading the settings file
# ------------------------------------------------------------------------------

TFVARS_TEXT = """\
# comment = "ignored"
run_mode = "on_demand"
site_host   =   "antiproxypr.duckdns.org"
alert_email = "owner@example.org"
atlas_org_id = "0123456789abcdef01234567"
# acme_ca = "https://acme-staging-v02.api.letsencrypt.org/directory"
"""


def test_the_settings_file_is_read_and_commented_lines_are_not():
    values = common.parse_tfvars(TFVARS_TEXT)
    assert values == {
        "run_mode": "on_demand",
        "site_host": "antiproxypr.duckdns.org",
        "alert_email": "owner@example.org",
        "atlas_org_id": "0123456789abcdef01234567",
    }
    # Windows line endings change nothing.
    assert common.parse_tfvars(TFVARS_TEXT.replace("\n", "\r\n")) == values


def _preflight_settings(monkeypatch, tmp_path, text: str | None, capsys) -> tuple[int, str]:
    terraform_dir = tmp_path / "infra" / "terraform"
    terraform_dir.mkdir(parents=True, exist_ok=True)
    tfvars = terraform_dir / "terraform.tfvars"
    if text is not None:
        tfvars.write_text(text, encoding="utf-8")
    monkeypatch.setattr(preflight, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(preflight, "TF_DIR", terraform_dir)
    monkeypatch.setattr(preflight, "TFVARS", tfvars)
    # git answers "ignored" and "nothing tracked".
    monkeypatch.setattr(preflight, "quiet", lambda cmd: (0, ""))
    report = preflight.Report()
    preflight.check_tfvars(report)
    return report.missing, capsys.readouterr().out


def test_preflight_says_the_staging_line_is_off_while_it_is_commented_out(monkeypatch, tmp_path, capsys):
    missing, printed = _preflight_settings(monkeypatch, tmp_path, TFVARS_TEXT, capsys)
    assert missing == 1
    assert "the staging certificate line is not on" in printed
    assert "site_host is set" in printed and "atlas_org_id is set" in printed


def test_preflight_passes_a_complete_settings_file(monkeypatch, tmp_path, capsys):
    text = TFVARS_TEXT.replace("# acme_ca", "acme_ca")
    missing, printed = _preflight_settings(monkeypatch, tmp_path, text, capsys)
    assert missing == 0
    assert "staging certificate authority is on" in printed


def test_preflight_names_example_values_that_were_not_replaced(monkeypatch, tmp_path, capsys):
    example = (SCRIPTS.parent / "terraform" / "terraform.tfvars.example").read_text(encoding="utf-8")
    missing, printed = _preflight_settings(monkeypatch, tmp_path, example, capsys)
    assert "site_host still has the example value" in printed
    assert "alert_email still has the example value" in printed
    assert "atlas_org_id still has the example value" in printed
    assert missing == 4  # the three values and the staging line


def test_preflight_finds_a_settings_file_left_in_the_wrong_folder(monkeypatch, tmp_path, capsys):
    (tmp_path / "terraform.tfvars").write_text(TFVARS_TEXT, encoding="utf-8")
    missing, printed = _preflight_settings(monkeypatch, tmp_path, None, capsys)
    assert missing == 1
    assert "terraform.tfvars is in the wrong place" in printed
    assert "Move-Item" in printed


def test_preflight_never_prints_the_atlas_keys(monkeypatch, capsys):
    monkeypatch.setenv("MONGODB_ATLAS_PUBLIC_API_KEY", "public-key-value")
    monkeypatch.setenv("MONGODB_ATLAS_PRIVATE_API_KEY", SECRET)
    report = preflight.Report()
    # The example organization id: the keys are reported as set, and no request is made.
    preflight.check_atlas(report, {"atlas_org_id": preflight.PLACEHOLDERS["atlas_org_id"]})
    printed = capsys.readouterr().out
    assert "both Atlas API key variables are set" in printed
    assert SECRET not in printed and "public-key-value" not in printed


# ------------------------------------------------------------------------------
# Switching the certificate authority
# ------------------------------------------------------------------------------


def test_the_certificate_command_follows_the_settings_file():
    import tf

    kind, commands = tf.certificate_commands(TFVARS_TEXT)  # the staging line is commented out
    assert kind == "real"
    assert any("ACME_CA=https://acme-v02.api.letsencrypt.org/directory" in line for line in commands)

    kind, commands = tf.certificate_commands(TFVARS_TEXT.replace("# acme_ca", "acme_ca"))
    assert kind == "staging"
    assert any("acme-staging-v02" in line for line in commands)
    # Certificates from the other authority are removed and the site restarted.
    assert any("anti_proxy_caddy_data" in line for line in commands)
    assert "systemctl restart antiproxy.service" in commands


def test_the_certificate_command_refuses_any_other_address():
    import tf

    with pytest.raises(SystemExit):
        tf.certificate_commands('acme_ca = "https://example.org/x; rm -rf /"')


def test_preflight_accepts_the_real_certificate_authority_once_the_deployment_exists(monkeypatch, tmp_path, capsys):
    """After the switch to the real certificate the staging line is off on purpose."""
    state = tmp_path / "infra" / "terraform"
    state.mkdir(parents=True)
    (state / "terraform.tfstate").write_text(json.dumps({"resources": [{"type": "aws_instance"}]}), encoding="utf-8")
    missing, printed = _preflight_settings(monkeypatch, tmp_path, TFVARS_TEXT, capsys)
    assert missing == 0
    assert "real certificate authority" in printed
    assert "the staging certificate line is not on" not in printed


# ------------------------------------------------------------------------------
# After a start: catch up with merges made while the instance was stopped
# ------------------------------------------------------------------------------

OLD = "a" * 40
NEW = "b" * 40
OUT = {"instance_id": "i-0", "aws_region": "ap-south-1", "deploy_document": "antiproxy-prod-deploy"}


def _catch_up(monkeypatch, *, running: str, newest: str, unpublished):
    import tf

    deployed: list[dict] = []
    monkeypatch.setattr(tf, "outputs", lambda: OUT)
    monkeypatch.setattr(tf, "release_sha", lambda: newest)
    monkeypatch.setattr(tf, "running_release", lambda out: running)
    monkeypatch.setattr(preflight, "unpublished_images", lambda sha: unpublished)
    monkeypatch.setattr(
        tf, "run_on_instance",
        lambda out, document, parameters, wait_seconds: deployed.append({"document": document, **parameters}) or 0,
    )
    return tf.catch_up(), deployed


def test_start_deploys_the_newest_release_when_the_instance_is_behind(monkeypatch, capsys):
    code, deployed = _catch_up(monkeypatch, running=OLD, newest=NEW, unpublished=[])
    assert code == 0
    assert deployed == [{"document": "antiproxy-prod-deploy", "ReleaseSha": [NEW]}]


def test_start_does_nothing_when_the_instance_is_already_on_the_newest_release(monkeypatch, capsys):
    code, deployed = _catch_up(monkeypatch, running=NEW, newest=NEW, unpublished=[])
    assert code == 0 and deployed == []
    assert "newest release" in capsys.readouterr().out


def test_start_stays_on_the_current_release_while_the_new_images_are_not_published(monkeypatch, capsys):
    for unpublished in (["vision"], None):  # one image missing; registry unreachable
        code, deployed = _catch_up(monkeypatch, running=OLD, newest=NEW, unpublished=unpublished)
        assert code == 0 and deployed == []
        assert "Staying on the current release" in capsys.readouterr().out


def test_the_deploy_role_names_the_repository_by_its_permanent_ids():
    terraform = SCRIPTS.parent / "terraform"
    deploy = (terraform / "deploy.tf").read_text(encoding="utf-8")
    variables = (terraform / "variables.tf").read_text(encoding="utf-8")
    assert '"${var.github_oidc_subject_prefix}:ref:refs/heads/main"' in deploy
    assert "StringEquals" in deploy and "StringLike" not in deploy
    assert 'default     = "repo:krishtewatia@152677838/anti_proxy_attendance@1376867618"' in variables


def test_the_pipeline_fails_clearly_and_sends_nothing_when_the_instance_is_stopped():
    workflow = (SCRIPTS.parents[1] / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    check = workflow.index("- name: Is the instance running?")
    deploy = workflow.index("- name: Deploy this commit")
    step = workflow[check:deploy]
    assert 'if [ "$state" != "running" ]; then' in step and "exit 1" in step
    assert "Not deployed: the instance is $state. Nothing was changed." in step
    # The check comes before the only step that talks to the instance.
    assert "send-command" not in step and "send-command" in workflow[deploy:]
