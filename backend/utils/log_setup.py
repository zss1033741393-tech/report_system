import logging, os
from logging.handlers import TimedRotatingFileHandler

_initialized = False

def setup_logging(log_dir="./data/logs", level="DEBUG"):
    global _initialized
    if _initialized: return
    _initialized = True
    os.makedirs(log_dir, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    fmt = logging.Formatter("%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    ch = logging.StreamHandler(); ch.setLevel(logging.INFO); ch.setFormatter(fmt); root.addHandler(ch)
    fh = TimedRotatingFileHandler(os.path.join(log_dir,"trace.log"), when="midnight", backupCount=30, encoding="utf-8")
    fh.suffix = "%Y-%m-%d"; fh.setLevel(getattr(logging,level.upper(),logging.DEBUG)); fh.setFormatter(fmt); root.addHandler(fh)
    logging.getLogger("trace").propagate = True
    logging.getLogger(__name__).info(f"日志初始化: {log_dir}/trace.log")
