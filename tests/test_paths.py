"""路径与凭据测试：确保"打包后写用户目录"这条逻辑不会退化。"""

from __future__ import annotations

import os
from pathlib import Path

from chem_inspect import credentials, paths
from chem_inspect.settings import Settings


def test_app_home_defaults_to_project_root_in_dev() -> None:
    assert paths.app_home() == paths.project_root()


def test_app_home_honors_env_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHEM_INSPECT_HOME", str(tmp_path))
    assert paths.app_home() == tmp_path.resolve()


def test_save_and_load_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHEM_INSPECT_HOME", str(tmp_path))
    monkeypatch.delenv("MAAS_API_KEY", raising=False)

    assert credentials.load_api_key() == ""
    saved = credentials.save_api_key("sk-ws-test-1234567890")
    assert saved.exists()
    assert credentials.load_api_key() == "sk-ws-test-1234567890"

    if os.name != "nt":  # Windows 忽略 POSIX 权限位
        assert (saved.stat().st_mode & 0o777) == 0o600


def test_env_var_beats_config_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHEM_INSPECT_HOME", str(tmp_path))
    credentials.save_api_key("from-config")
    monkeypatch.setenv("MAAS_API_KEY", "from-env")
    assert credentials.load_api_key() == "from-env"


def test_settings_reads_key_from_user_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHEM_INSPECT_HOME", str(tmp_path))
    monkeypatch.delenv("MAAS_API_KEY", raising=False)
    credentials.save_api_key("sk-ws-from-json")

    settings = Settings(
        maas_api_key="",
        data_dir=tmp_path / "data",
        config_dir=Path("config"),
    )
    assert settings.maas_api_key == "sk-ws-from-json"
    assert settings.has_key is True


def test_settings_data_dir_follows_app_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHEM_INSPECT_HOME", str(tmp_path))
    settings = Settings(maas_api_key="sk-test")
    assert settings.data_dir == tmp_path.resolve() / "data"


def test_mask() -> None:
    assert credentials.mask("") == "（未配置）"
    assert credentials.mask("short") == "***"
    assert credentials.mask("sk-ws-abcdefghijklmno") == "sk-ws-a***lmno"
