"""Files the commands read and write: local paths and gs:// URLs alike, under the user's Google credentials."""

from __future__ import annotations

import cloudpathlib


class CloudStorage:
    def read_text(self, location: str) -> str:
        return cloudpathlib.AnyPath(location).read_text(encoding='utf-8')

    def write_text(self, location: str, text: str) -> None:
        cloudpathlib.AnyPath(location).write_text(text, encoding='utf-8')

    def is_file(self, location: str) -> bool:
        return cloudpathlib.AnyPath(location).is_file()

    def size(self, location: str) -> int:
        path = cloudpathlib.AnyPath(location)
        # A missing GCS object fails stat() with cloudpathlib's NoStatError, not FileNotFoundError.
        if not path.is_file():
            raise FileNotFoundError(location)
        return path.stat().st_size
