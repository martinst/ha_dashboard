import json
import logging
import logging.config
from pathlib import Path


def test_uvicorn_log_config_formats_access_and_app_records(capsys):
    cfg = json.loads((Path(__file__).parent.parent / "log_config.json").read_text())
    logging.config.dictConfig(cfg)
    try:
        # Exactly how uvicorn emits access lines (fields derived from args).
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d', "172.30.32.1:1234", "GET", "/api/state", "1.1", 502
        )
        logging.getLogger("app.main").warning("GET /api/state -> 502: boom")
    finally:
        logging.config.dictConfig({"version": 1, "disable_existing_loggers": False})
    out = capsys.readouterr()
    assert "Logging error" not in out.err
    assert "KeyError" not in out.err
    assert '172.30.32.1:1234 - "GET /api/state HTTP/1.1" 502' in out.out
    assert "WARNING app.main: GET /api/state -> 502: boom" in out.err
    assert out.out.startswith("20")  # timestamped
