"""手动运行单个数据同步任务。

用法::

    python tools/run_sync.py <task_id>
    python tools/run_sync.py --list

任务 id 与调度器一致（见 app/services/scheduler.py 的 _DEFAULT_TASKS）。
相比 /api/scheduler/sync-all，它一次只跑一个任务，便于对连不上的数据源
单独设超时、避免整条链路被拖死。
"""
import os
import sys
import time

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

from app.db.session import SessionLocal  # noqa: E402
from app.services.scheduler import _DEFAULT_TASKS  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "--list"):
        print("用法: python tools/run_sync.py <task_id>")
        print("可用任务:")
        for k, v in _DEFAULT_TASKS.items():
            print(f"  {k:26s} {v['name']}")
        return 0 if sys.argv[1:] else 1

    task_id = sys.argv[1]
    definition = _DEFAULT_TASKS.get(task_id)
    if definition is None:
        print(f"FAIL 未知任务: {task_id}")
        return 1

    db = SessionLocal()
    started = time.time()
    try:
        definition["fn"](db)
        print(f"OK   {task_id}  耗时 {time.time() - started:.1f}s")
        return 0
    except Exception as exc:
        print(f"FAIL {task_id}  耗时 {time.time() - started:.1f}s  "
              f"{type(exc).__name__}: {str(exc)[:200]}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())