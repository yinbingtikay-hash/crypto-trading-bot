"""驗證 pid_lock.py：防止同一個 bot 被開多過一份 process。"""

import os

import pytest

import pid_lock


def test_acquire_creates_lock_file_with_own_pid(tmp_path):
    path = str(tmp_path / "bot.pid")
    pid_lock.acquire_singleton_lock(path)

    with open(path) as f:
        assert f.read().strip() == str(os.getpid())


def test_acquire_overwrites_stale_lock_from_dead_process(tmp_path):
    path = str(tmp_path / "bot.pid")
    # 用一個實際上唔存在嘅超大PID模擬「舊process已經死咗」
    with open(path, "w") as f:
        f.write("999999")

    pid_lock.acquire_singleton_lock(path)  # 唔應該拋錯/exit

    with open(path) as f:
        assert f.read().strip() == str(os.getpid())


def test_acquire_refuses_when_another_process_alive(tmp_path):
    path = str(tmp_path / "bot.pid")
    # PID 1 (launchd/init) 喺任何 Unix 系統都實際存在，模擬「另一個process生存緊」
    with open(path, "w") as f:
        f.write("1")

    with pytest.raises(SystemExit):
        pid_lock.acquire_singleton_lock(path)


def test_release_removes_lock_when_owned_by_self(tmp_path):
    path = str(tmp_path / "bot.pid")
    pid_lock.acquire_singleton_lock(path)

    pid_lock.release_singleton_lock(path)

    assert not os.path.exists(path)


def test_release_does_not_remove_lock_owned_by_other_pid(tmp_path):
    path = str(tmp_path / "bot.pid")
    with open(path, "w") as f:
        f.write("999999")  # 唔係自己個PID

    pid_lock.release_singleton_lock(path)

    assert os.path.exists(path)  # 唔應該亂咁刪走第二個process嘅鎖


def test_release_is_noop_when_file_missing(tmp_path):
    path = str(tmp_path / "does_not_exist.pid")
    pid_lock.release_singleton_lock(path)  # 唔應該拋錯
