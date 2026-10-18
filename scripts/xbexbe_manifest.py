"""Record XboxXBERecomp build inputs immediately after a successful build."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tomllib

from build_manifest import (CONFIGURATIONS, ROOT, ProvenanceError, checked_file,
                            file_record, git_bytes, read_json, tree_record, valid_digest)


def collect_manifest(root: Path, configuration: str, release: bool = False) -> tuple[dict, dict[str, bytes]]:
    if configuration not in CONFIGURATIONS:
        raise ProvenanceError(f"Unsupported configuration: {configuration}")
    root = root.resolve()
    profile_directory = "xbexbe-release" if release else "xbexbe"
    output = root / "build" / profile_directory
    if release and "DARKWATCH_RELEASE:BOOL=TRUE" not in (output / "CMakeCache.txt").read_text(encoding="utf-8"):
        raise ProvenanceError("Release build must enable DARKWATCH_RELEASE")
    project = root / "xbexbe"
    pin, pin_file = read_json(root, root / "config/xbexbe-toolchain.json")
    xbe = file_record(root, root / "game_files/default.xbe")
    if not valid_digest(pin.get("xbe_sha256")) or xbe["sha256"] != pin["xbe_sha256"]:
        raise ProvenanceError("Actual XBE SHA256 does not match the configured binary identity")

    toolkit = root / "third_party/XboxXBERecomp"
    revision = git_bytes(toolkit, "rev-parse", "HEAD").decode("ascii").strip()
    if revision != pin.get("commit"):
        raise ProvenanceError("Configured and checked-out XboxXBERecomp revisions must match")
    patch = git_bytes(toolkit, "diff", "--binary", "--no-ext-diff", "--no-textconv", "HEAD")
    untracked = git_bytes(toolkit, "ls-files", "--others", "--exclude-standard", "-z")
    untracked_paths = [toolkit / name.decode("utf-8") for name in untracked.split(b"\0") if name]

    project_config = file_record(root, project / "config/game.toml")
    config_bytes = (project / "config/game.toml").read_bytes()
    if hashlib.sha256(config_bytes).hexdigest() != project_config["sha256"]:
        raise ProvenanceError("Game configuration changed while reading")
    config = tomllib.loads(config_bytes.decode("utf-8"))
    image = config.get("xbe", {})
    if image.get("out") != "generated/game":
        raise ProvenanceError("Game configuration must generate into generated/game")
    source = image.get("path")
    if not isinstance(source, str):
        raise ProvenanceError("Game configuration has no XBE input path")
    source_path = (project / source).resolve()
    if not source_path.is_relative_to(root):
        raise ProvenanceError("Configured XBE input is outside the workspace")
    source_xbe = file_record(root, source_path)
    if source_xbe["sha256"] != xbe["sha256"]:
        raise ProvenanceError("Configured build input differs from the pinned original XBE")

    partitions = image.get("partitions")
    if type(partitions) is not int or partitions < 1:
        raise ProvenanceError("Game configuration has no positive partition count")
    generated_root = project / "generated/game"
    for name in ("x86_func_mapping.cpp", "x86_recomp_shared.h", "image_symbols.h"):
        checked_file(generated_root / name)
    for index in range(partitions):
        checked_file(generated_root / f"x86_recomp.{index}.cpp")
    generated = tree_record(root, [p for p in generated_root.rglob("*") if p.is_file()])

    executable = file_record(root, output / "darkwatch_xbe.exe")
    symbols = file_record(root, output / "darkwatch_xbe.pdb")
    if not executable["size"] or not symbols["size"]:
        raise ProvenanceError("Executable and matching symbol file must be nonempty")
    host_paths = [p for p in (project / "src").rglob("*") if p.is_file()]
    host_paths += [p for p in (project / "config").rglob("*") if p.is_file()]
    checked_file(project / "src/common/game_info.cpp")
    host_paths += [project / "CMakeLists.txt", output / "darkwatch_xbe_xbe.cpp", output / "CMakeCache.txt"]

    dependencies = []
    for name in ("zydis", "tomlplusplus", "imgui", "sdl3"):
        dependency = root / "build/xbexbe/_deps" / f"{name}-src"
        status = git_bytes(dependency, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none").decode("utf-8")
        submodules = git_bytes(dependency, "submodule", "status", "--recursive").decode("utf-8")
        if status or any(line and line[0] != " " for line in submodules.splitlines()):
            raise ProvenanceError(f"Dependency tree must be clean with initialized matching submodules: {dependency}")
        dependencies.append({
            "path": dependency.relative_to(root).as_posix(),
            "checkout_revision": git_bytes(dependency, "rev-parse", "HEAD").decode("ascii").strip(),
            "working_tree_status": status,
            "submodules": submodules,
        })

    manifest = {
        "schema_version": 1,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "configuration": configuration,
        "executable": executable,
        "symbols": symbols,
        "xbe": xbe,
        "xbe_build_input": source_xbe,
        "project_config": project_config,
        "generated_sources": generated,
        "host_sources": tree_record(root, host_paths),
        "hd_ui_assets": file_record(root, output / "hd-ui.pack"),
        "hd_ui_sources": tree_record(root, [p for p in (project / "hd_ui").rglob("*") if p.is_file()]),
        "toolchain": {
            "name": "XboxXBERecomp", "configured_pin_file": pin_file, "configured_pin": pin,
            "checkout_revision": revision,
            "build_patch": {"path": f"build/{profile_directory}/build-toolchain.patch",
                            "sha256": hashlib.sha256(patch).hexdigest(), "size": len(patch)},
            "untracked_files": tree_record(root, untracked_paths),
        },
        "dependencies": dependencies,
        "capture_script": file_record(root, root / "scripts/xbexbe_manifest.py"),
        "hash_helpers": file_record(root, root / "scripts/build_manifest.py"),
        "scope": "Inputs captured immediately after the build; not runtime equivalence or translation-completeness evidence.",
    }
    if release:
        manifest["release_profile"] = {"name": "release-candidate", "diagnostics": False, "strict_assets": True}
    pipeline_path = root / "analysis" / profile_directory / "pipeline-latest.json"
    if pipeline_path.exists():
        pipeline, pipeline_file = read_json(root, pipeline_path)
        manifest["pipeline"] = {"source_file": pipeline_file, "record": pipeline}
    return manifest, {"build-toolchain.patch": patch}


def write_manifest(root: Path, configuration: str, release: bool = False) -> Path:
    manifest, artifacts = collect_manifest(root, configuration, release)
    output = root / "build" / ("xbexbe-release" if release else "xbexbe")
    destination = output / "build-manifest.json"
    temporary = output / "build-manifest.json.tmp"
    for path in (destination, temporary, *(output / name for name in artifacts)):
        if path.is_symlink():
            raise ProvenanceError(f"Output is a symbolic link: {path}")
    for name, data in artifacts.items():
        (output / name).write_bytes(data)
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", choices=CONFIGURATIONS, default="RelWithDebInfo")
    parser.add_argument("--release", action="store_true", help="Record the separate quiet launcher build")
    args = parser.parse_args()
    try:
        destination = write_manifest(ROOT, args.configuration, args.release)
    except (ProvenanceError, OSError, UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        print(f"XboxXBERecomp build provenance failed: {exc}", file=sys.stderr)
        return 1
    print(f"XboxXBERecomp build provenance: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
