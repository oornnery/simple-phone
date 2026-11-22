"""Validate release metadata/wheels using only the Python standard library."""

import argparse
import ast
import re
from email.parser import Parser
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"


def project_version():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = text.split("[project]\n", 1)[1].split("\n[", 1)[0]
    match = re.search(r'^version\s*=\s*"([^"]+)"', project, re.MULTILINE)
    if not match:
        raise ValueError("Expected a static project.version in pyproject.toml")
    version = match[1]
    tree = ast.parse((SOURCE / "simple_phone/version.py").read_text())
    exported = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
    )
    if version != exported:
        raise ValueError(
            f"Version mismatch: pyproject={version}, __version__={exported}"
        )
    return version


def clean_build():
    # Remove only stale generated Python modules, preserving native libraries
    # and object files so a routine wheel build can reuse expensive compilation.
    for directory in (ROOT / "build").glob("lib.*"):
        for module in directory.rglob("*.py"):
            relative = module.relative_to(directory)
            if (
                relative.parts[0] == "simple_phone"
                and not (SOURCE / relative).is_file()
            ):
                module.unlink()
                print(f"Removed obsolete build module: {relative}")


def check_wheel(path, version):
    with ZipFile(path) as archive:
        names = set(archive.namelist())
        required = {
            "simple_phone/__init__.py",
            "simple_phone/core/engine.py",
            "simple_phone/phone.py",
            "simple_phone/_native/pjsua2.py",
            "simple_phone/_native/_build.py",
        }
        if required - names:
            raise ValueError(f"{path}: missing {sorted(required - names)}")
        if not any(
            n.startswith("simple_phone/_native/_pjsua2.") and n.endswith(".so")
            for n in names
        ):
            raise ValueError(f"{path}: native extension missing")
        forbidden = [n for n in names if n.endswith((".cpp", ".h", ".pyc"))]
        if forbidden:
            raise ValueError(
                f"{path}: generated source/cache files included: {forbidden}"
            )
        metadata_path = next(n for n in names if n.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(archive.read(metadata_path).decode())
        if metadata["Name"] != "simple-phone" or metadata["Version"] != version:
            raise ValueError(f"{path}: package name/version differs from project")
        if set(metadata.get_all("Provides-Extra", [])) != {"stt", "tts"}:
            raise ValueError(f"{path}: unexpected extras")
        entry_points = next(
            n for n in names if n.endswith(".dist-info/entry_points.txt")
        )
        if (
            "simple-phone = simple_phone.cli:main"
            not in archive.read(entry_points).decode()
        ):
            raise ValueError(f"{path}: simple-phone command missing")
        expected = {
            str(p.relative_to(SOURCE))
            for p in (SOURCE / "simple_phone").rglob("*.py")
            if "__pycache__" not in p.parts
        }
        # cibuildwheel generates these inside the Linux build container, while
        # this validator may run on a host checkout with no generated binding.
        expected |= {
            "simple_phone/_native/pjsua2.py",
            "simple_phone/_native/_build.py",
        }
        actual = {
            n for n in names if n.startswith("simple_phone/") and n.endswith(".py")
        }
        if actual != expected:
            raise ValueError(
                f"{path}: obsolete/missing modules: {sorted(actual ^ expected)}"
            )
    print(f"OK: {path.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--metadata", action="store_true")
    mode.add_argument("--clean-build", action="store_true")
    parser.add_argument("wheels", nargs="*", type=Path)
    parser.add_argument(
        "--tag", help="require a release tag matching v<project.version>"
    )
    args = parser.parse_args()
    version = project_version()
    if args.tag is not None and args.tag != f"v{version}":
        parser.error(f"tag must be v{version}, received {args.tag!r}")
    if args.clean_build:
        clean_build()
    elif args.metadata:
        print(f"OK: metadata/version {version}")
    else:
        wheels = args.wheels or sorted((ROOT / "dist").glob("simple_phone-*.whl"))
        if not wheels:
            parser.error("no wheels found; run bash scripts/build.sh first")
        for wheel in wheels:
            check_wheel(wheel, version)


if __name__ == "__main__":
    main()
