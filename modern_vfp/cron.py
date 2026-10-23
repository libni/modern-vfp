"""
Motor de Planificación y Tareas Programadas (In-Memory Cron Scheduler) (`modern_vfp/cron.py`) para FoxNext.
Permite programar la ejecución recurrente de rutinas, scripts o mantenimiento de bases de datos:
- `SCHEDULE TASK <nombre> EVERY <n> (SECONDS|MINUTES|HOURS) DO <comando_o_prg>`
- `CANCEL TASK <nombre>`
- `RUN PENDING TASKS`
- Función: `TASKSTATUS([cNombreTarea [, cCursorDestino]])`
"""

from __future__ import annotations
import datetime
import time
from typing import Any, Dict, List, Optional

from .cursor import Cursor, FieldDef


class ScheduledTask:
    def __init__(self, name: str, interval_seconds: float, target_command: str) -> None:
        self.name = name.lower().strip()
        self.interval_seconds = float(interval_seconds)
        self.target_command = target_command.strip()
        self.created_at = datetime.datetime.now().isoformat()
        self.last_run_epoch: Optional[float] = None
        self.next_run_epoch: float = time.time() + self.interval_seconds
        self.run_count: int = 0
        self.last_status: str = "PENDING"
        self.last_error: str = ""

    def is_due(self, now: float) -> bool:
        return now >= self.next_run_epoch

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "interval_sec": self.interval_seconds,
            "command": self.target_command,
            "run_count": self.run_count,
            "status": self.last_status,
            "last_run": datetime.datetime.fromtimestamp(self.last_run_epoch).isoformat() if self.last_run_epoch else "",
            "next_run": datetime.datetime.fromtimestamp(self.next_run_epoch).isoformat(),
            "error": self.last_error,
        }


class TaskScheduler:
    """Administrador de tareas programadas en memoria."""

    def __init__(self) -> None:
        # name -> ScheduledTask
        self._tasks: Dict[str, ScheduledTask] = {}

    def schedule(self, name: str, interval_seconds: float, target_command: str) -> ScheduledTask:
        k = name.lower().strip()
        task = ScheduledTask(k, interval_seconds, target_command)
        self._tasks[k] = task
        return task

    def cancel(self, name: str) -> bool:
        k = name.lower().strip()
        if k in self._tasks:
            del self._tasks[k]
            return True
        return False

    def clear(self) -> None:
        self._tasks.clear()

    def run_pending(self, interpreter: Any) -> int:
        """Ejecuta de forma síncrona todas las tareas cuyo vencimiento haya expirado."""
        now = time.time()
        executed = 0
        for task in list(self._tasks.values()):
            if task.is_due(now):
                task.last_run_epoch = now
                task.run_count += 1
                try:
                    interpreter.execute(task.target_command)
                    task.last_status = "OK"
                    task.last_error = ""
                except Exception as ex:
                    task.last_status = "ERROR"
                    task.last_error = str(ex)
                task.next_run_epoch = now + task.interval_seconds
                executed += 1
        return executed

    def to_cursor(self, task_name: Optional[str] = None, into_alias: str = "tasks_status") -> Cursor:
        """Genera un cursor con el estado de las tareas registradas."""
        fields = [
            FieldDef("task_name", "C", 30, 0),
            FieldDef("interval_s", "I", 10, 0),
            FieldDef("run_count", "I", 10, 0),
            FieldDef("status", "C", 12, 0),
            FieldDef("command", "C", 120, 0),
            FieldDef("last_run", "C", 30, 0),
            FieldDef("next_run", "C", 30, 0),
        ]
        cur = Cursor(into_alias.lower().strip(), fields)
        target_tasks = [self._tasks[task_name.lower().strip()]] if task_name and task_name.lower().strip() in self._tasks else list(self._tasks.values())

        for t in target_tasks:
            d = t.to_dict()
            cur.append_dict(
                {
                    "task_name": d["name"],
                    "interval_s": int(d["interval_sec"]),
                    "run_count": d["run_count"],
                    "status": d["status"],
                    "command": d["command"],
                    "last_run": d["last_run"],
                    "next_run": d["next_run"],
                }
            )
        cur.go_top()
        return cur
