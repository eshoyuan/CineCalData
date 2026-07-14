#!/usr/bin/env python3
"""Load local build credentials from environment or the macOS Keychain."""

from __future__ import annotations

import getpass
import os
import platform
import subprocess


KEYCHAIN_SERVICES = {
    "MODEL_API_KEY": "CineCalMetaAI",
    "TMDB_API_TOKEN": "CineCalTMDB",
    "TMDB_API_KEY": "CineCalTMDBAPIKey",
}


def read_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    service = KEYCHAIN_SERVICES.get(name)
    if not service or platform.system() != "Darwin":
        return ""
    try:
        return subprocess.check_output(
            [
                "security",
                "find-generic-password",
                "-a",
                getpass.getuser(),
                "-s",
                service,
                "-w",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""
