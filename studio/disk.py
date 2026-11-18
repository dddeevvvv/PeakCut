"""Keeps the drive from filling up while PeakCut records.

Three things, every five minutes:
- A clip's source cut (and a video's downloaded file) is deleted KEEP_HOURS after it was made. The finished
  clip and its cover stay. After that, a live clip can no longer be re-trimmed; a linked video's clip still can,
  because the piece is downloaded again.
- The buffer of a recording that has ended is deleted (a restart can leave one behind).
- Below STOP_GB free, running recordings stop cleanly; their clips are kept. New recordings do not start below
  START_GB (see live.start_session and load.disk_full)."""
import shutil
import threading
import time
from pathlib import Path

from . import config, ctx

KEEP_HOURS = float(config.env("PEAKCUT_KEEP_SOURCE_HOURS", "48"))
START_GB = float(config.env("PEAKCUT_MIN_FREE_DISK_GB", "10"))
STOP_GB = float(config.env("PEAKCUT_STOP_DISK_GB", "5"))
_started = {"on": False}


def free_gb() -> float:
    try:
        return shutil.disk_usage(config.DATA_DIR).free / 1e9
    except OSError:
        return 999.0


def _old(path: Path, now: float) -> bool:
    try:
        return now - path.stat().st_mtime > KEEP_HOURS * 3600
    except OSError:
        return False


def sweep(now=None) -> int:
    """One round of clean-up. Returns the bytes freed."""
    from . import jobs, live
    now = now or time.time()
    freed = 0
    running = {s.job["id"] for s in live.SESSIONS.values() if not s.finished}
    for job in jobs.all_jobs():
        changed = False
        busy = any(c.get("status") in ("queued", "rendering") for c in job.get("clips", []))
        for c in job.get("clips", []):
            src = c.get("src")
            if src and c.get("status") in ("done", "error") and now - float(c.get("made_at") or now) > KEEP_HOURS * 3600:
                p = Path(src)
                if p.exists():
                    freed += p.stat().st_size
                    p.unlink(missing_ok=True)
                for k in ("src", "src_offset", "src_end"):
                    c.pop(k, None)
                c["src_gone"] = True
                changed = True
        sp = job.get("source_path")
        if sp and job.get("kind") == "video" and job.get("status") in ("done", "error") and not busy \
                and job.get("source", {}).get("type") == "url" and _old(Path(sp), now):
            p = Path(sp)
            freed += p.stat().st_size if p.exists() else 0
            p.unlink(missing_ok=True)
            job.pop("source_path", None)
            changed = True
        if job.get("kind") == "live" and job["id"] not in running and not job.get("recover"):
            buf = Path(job["dir"]) / "buffer"
            for f in buf.glob("*") if buf.is_dir() else []:
                try:
                    freed += f.stat().st_size
                    f.unlink()
                except OSError:
                    pass
        if changed:
            jobs.save(job)
    return freed


def guard():
    """Stop running recordings when the drive is nearly full: a full drive breaks every recording at once."""
    from . import alerts, live
    if free_gb() >= STOP_GB:
        return
    for s in list(live.active()):
        with ctx.as_user(s.job["user"]):
            s.stop(f"Stopped: the drive is almost full ({free_gb():.1f} GB left)")
            alerts.notify(f"recording of {s.job.get('uploader') or 'a stream'} stopped: the drive has only "
                          f"{free_gb():.1f} GB left. Its clips are kept.")


def _loop():
    time.sleep(60)
    while True:
        try:
            guard()
            sweep()
        except Exception:  # noqa: BLE001 - clean-up must never take the server down
            pass
        time.sleep(300)


def start():
    if not _started["on"]:
        _started["on"] = True
        threading.Thread(target=_loop, daemon=True, name="disk").start()
