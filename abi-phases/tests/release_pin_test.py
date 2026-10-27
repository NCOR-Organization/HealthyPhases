"""The Nexus web image and the .abi submodule must name the same ABI release.

The API runs from the submodule and the web app from the prebuilt image, so a
bump that moves only one of them pairs a frontend with an API it was not built
against.
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _submodule_release() -> str:
    pyproject = ROOT / ".abi" / "libs" / "naas-abi" / "pyproject.toml"
    return tomllib.loads(pyproject.read_text())["project"]["version"]


def _nexus_web_tag() -> str:
    compose = (ROOT / "docker-compose.yml").read_text()
    match = re.search(r"^\s*image:\s*ghcr\.io/jupyter-naas/nexus-web:(\S+)\s*$", compose, re.M)
    assert match, "nexus-web image must be pinned in docker-compose.yml"
    return match.group(1)


def test_nexus_web_image_matches_abi_submodule() -> None:
    assert _nexus_web_tag() == f"naas-abi-v{_submodule_release()}"


def test_project_requires_the_submodule_release() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert f"naas-abi>={_submodule_release()}" in project["dependencies"]
