"""Small, independent local preferences with bounded reads and atomic writes."""

from os import getenv
from pathlib import Path
from tempfile import NamedTemporaryFile


def preference_path(name):
    app_data = Path(getenv("LOCALAPPDATA", ""))
    return app_data / "NosePointer" / f"{name}.txt" if app_data.is_absolute() else None


def read_preference(name, limit):
    path = preference_path(name)
    if path is None:
        return b""
    try:
        with path.open("rb") as preference:
            return preference.read(limit)
    except OSError:
        return b""


def load_text_preference(name):
    value = read_preference(name, 33)
    if len(value) > 32:
        return ""
    if value.endswith(b"\n"):
        value = value[:-1].removesuffix(b"\r")
    try:
        return value.decode("ascii")
    except UnicodeDecodeError:
        return ""


def save_preference(name, value):
    path = preference_path(name)
    if path is None:
        return
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, prefix=f"{name}-", delete=False) as preference:
            temporary = Path(preference.name)
            preference.write(f"{value}\n".encode("ascii"))
        temporary.replace(path)
    except OSError:
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
