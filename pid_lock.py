"""防止同一個 bot 被開多過一份 process 同時運行。

背景：曾經因為手動重啟時舊 process 冇真正死清，搞到兩個「殭屍」process
喺背景各自獨立跑咗 2 日都冇人知，各自落單、各自回覆 Telegram 指令，
搞到帳目同回覆全部亂晒。加呢層鎖之後，第二個 process 一啟動就會發現
已經有人跑緊，即刻拒絕開機，唔會再靜雞雞攞多份出嚟。
"""

import os
import sys


def acquire_singleton_lock(pid_file_path: str) -> None:
    if os.path.exists(pid_file_path):
        with open(pid_file_path) as f:
            old_pid_str = f.read().strip()

        if old_pid_str.isdigit():
            old_pid = int(old_pid_str)
            is_alive = True
            try:
                os.kill(old_pid, 0)  # 唔會真係殺，淨係check個process存唔存在
            except ProcessLookupError:
                is_alive = False  # 舊process已死，PID file係stale嘅，可以安全覆寫
            except PermissionError:
                pass  # 個PID存在但屬於第二個user——都當佢生存緊，安全至上

            if is_alive:
                print(
                    f"已經有一個 process（PID {old_pid}）running緊，拒絕開多一份。\n"
                    f"如果確定嗰個 process 已經死咗（例如電腦重開過），刪走 {pid_file_path} 再重試。",
                    file=sys.stderr,
                )
                sys.exit(1)

    os.makedirs(os.path.dirname(pid_file_path) or ".", exist_ok=True)
    with open(pid_file_path, "w") as f:
        f.write(str(os.getpid()))


def release_singleton_lock(pid_file_path: str) -> None:
    if not os.path.exists(pid_file_path):
        return
    with open(pid_file_path) as f:
        content = f.read().strip()
    if content == str(os.getpid()):
        os.remove(pid_file_path)
