import config


def test_numeric_env_helpers_fall_back_for_blank_values(monkeypatch):
    monkeypatch.setenv("ADINTEL_TEST_INT", "")
    monkeypatch.setenv("ADINTEL_TEST_FLOAT", "")

    assert config._env_int("ADINTEL_TEST_INT", 30) == 30
    assert config._env_float("ADINTEL_TEST_FLOAT", 50000) == 50000


def test_numeric_env_helpers_fall_back_for_invalid_values(monkeypatch):
    monkeypatch.setenv("ADINTEL_TEST_INT", "soon")
    monkeypatch.setenv("ADINTEL_TEST_FLOAT", "expensive")

    assert config._env_int("ADINTEL_TEST_INT", 30) == 30
    assert config._env_float("ADINTEL_TEST_FLOAT", 50000) == 50000
