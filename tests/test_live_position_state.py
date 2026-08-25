import live_position_state as position_state


def test_save_and_load_round_trip(tmp_path):
    path = str(tmp_path / "position.json")
    pos = position_state.PersistedPosition(
        side="BUY", entry_price=100.0, quantity=0.5, entry_time="2024-01-01T00:00:00+00:00",
        exit_due_after_funding_ts=1735689600,
    )
    position_state.save_position_state(path, pos)

    loaded = position_state.load_position_state(path)

    assert loaded.quantity == 0.5
    assert loaded.exit_due_after_funding_ts == 1735689600


def test_load_returns_none_when_missing(tmp_path):
    assert position_state.load_position_state(str(tmp_path / "nope.json")) is None


def test_clear_removes_file(tmp_path):
    path = str(tmp_path / "position.json")
    pos = position_state.PersistedPosition("BUY", 100.0, 0.5, "t", 123)
    position_state.save_position_state(path, pos)

    position_state.clear_position_state(path)

    assert position_state.load_position_state(path) is None
