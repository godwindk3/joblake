"""Snapshot installed runtime dependency closure; run after validated updates."""
from importlib.metadata import distribution
from pathlib import Path
import tomllib

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def main():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    pending = [Requirement(item) for item in project["project"]["dependencies"]]
    seen, pins = set(), {}
    while pending:
        req = pending.pop()
        name = canonicalize_name(req.name)
        dist = distribution(req.name)
        if req.specifier and dist.version not in req.specifier:
            raise RuntimeError(f"{name} {dist.version} does not satisfy {req.specifier}")
        pins[name] = dist.version
        key = (name, tuple(sorted(req.extras)))
        if key in seen:
            continue
        seen.add(key)
        for raw in dist.requires or []:
            child = Requirement(raw)
            include = child.marker is None
            for system, platform, os_name in [("Windows", "win32", "nt"), ("Linux", "linux", "posix")]:
                for extra in {"", *req.extras}:
                    env = default_environment()
                    env.update(platform_system=system, sys_platform=platform, os_name=os_name, extra=extra)
                    if child.marker is not None:
                        include = include or child.marker.evaluate(env)
            if include:
                pending.append(child)
    content = "# Installed runtime snapshot; regenerate with scripts/freeze_constraints.py.\n"
    content += "# Windows/Linux dependency union; validate installation on each target platform.\n"
    content += "".join(f"{name}=={version}\n" for name, version in sorted(pins.items()))
    (root / "constraints.txt").write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
