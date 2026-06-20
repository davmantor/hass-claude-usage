from datetime import UTC, datetime
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str) -> ModuleType:
    path = ROOT / relative_path
    if not path.exists():
        pytest.fail(f"{relative_path} does not exist")
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


const = load_module("hass_claude_usage_const", "custom_components/hass_claude_usage/const.py")


def helper_module() -> ModuleType:
    return load_module("hass_claude_usage_helpers", "custom_components/hass_claude_usage/helpers.py")


def test_parse_oauth_code_rejects_missing_state() -> None:
    helpers = helper_module()
    assert helpers.parse_oauth_code("auth-code", "expected-state") is None


def test_parse_oauth_code_rejects_mismatched_state() -> None:
    helpers = helper_module()
    assert helpers.parse_oauth_code("auth-code#wrong-state", "expected-state") is None


def test_parse_oauth_code_returns_code_when_state_matches() -> None:
    helpers = helper_module()
    assert helpers.parse_oauth_code("auth-code#expected-state", "expected-state") == "auth-code"


def test_parse_timestamp_converts_z_suffix_to_aware_datetime() -> None:
    helpers = helper_module()
    assert helpers.parse_timestamp("2026-06-20T12:30:00Z") == datetime(
        2026, 6, 20, 12, 30, tzinfo=UTC
    )


def test_parse_timestamp_rejects_naive_datetime() -> None:
    helpers = helper_module()
    assert helpers.parse_timestamp("2026-06-20T12:30:00") is None


def test_api_error_is_binary_problem_sensor_not_measurement_sensor() -> None:
    assert all(definition[0] != "api_error" for definition in const.SENSOR_DEFINITIONS)
    assert ("api_error", "API Error", "mdi:alert-circle", "problem") in const.BINARY_SENSOR_DEFINITIONS


def test_weekly_sonnet_sensors_are_not_created() -> None:
    sensor_keys = {definition[0] for definition in const.SENSOR_DEFINITIONS}
    assert "week_sonnet_usage_percent" not in sensor_keys
    assert "week_sonnet_reset_time" not in sensor_keys
