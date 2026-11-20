import os
from urllib.parse import quote

import requests
from qgis.PyQt.QtCore import QThread, pyqtSignal

TIMEOUT_SECONDS = 120


def error_text(response) -> str:
    """The server's error message of a failed response."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return str(detail) if detail else f"HTTP {response.status_code}"


class AllowedTypesFetcher(QThread):
    """Asks the server which file extensions a session accepts."""

    fetched = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, base_url: str, api_key: str, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key

    def run(self):
        try:
            response = requests.get(
                f"{self.base_url}/sessions/allowed-types",
                headers={"X-API-Key": self.api_key},
                timeout=TIMEOUT_SECONDS,
            )
            if response.status_code != 200:
                self.failed.emit(error_text(response))
                return
            self.fetched.emit(response.json().get("extensions", []))
        except requests.RequestException as e:
            self.failed.emit(str(e))


class FileUploader(QThread):
    """Uploads the attached files to the session, one after the other."""

    done = pyqtSignal(dict)  # file path -> error message; empty when all files were stored

    def __init__(self, base_url: str, api_key: str, session_id: str, paths: list, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key
        self.session_id = session_id
        self.paths = paths

    def run(self):
        failures = {}
        url = f"{self.base_url}/sessions/{quote(self.session_id, safe='')}/files"
        for path in self.paths:
            try:
                with open(path, "rb") as handle:
                    response = requests.post(
                        url,
                        headers={"X-API-Key": self.api_key},
                        files={"file": (os.path.basename(path), handle)},
                        timeout=TIMEOUT_SECONDS,
                    )
                if response.status_code != 201:
                    failures[path] = error_text(response)
            except (OSError, requests.RequestException) as e:
                failures[path] = str(e)
        self.done.emit(failures)
