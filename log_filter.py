"""Uvicorn log filter that strips token=... from access log URLs."""
import logging
import re

_TOKEN_RE = re.compile(r"(\btoken=)[^&\s\"]+", re.IGNORECASE)


class StripTokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # access logger formats args into record.args
        if record.args:
            new_args = []
            for a in record.args:
                if isinstance(a, str):
                    a = _TOKEN_RE.sub(r"\1<redacted>", a)
                new_args.append(a)
            record.args = tuple(new_args)
        if isinstance(record.msg, str):
            record.msg = _TOKEN_RE.sub(r"\1<redacted>", record.msg)
        return True


def install():
    for name in ("uvicorn.access", "uvicorn", "uvicorn.error"):
        logging.getLogger(name).addFilter(StripTokenFilter())
