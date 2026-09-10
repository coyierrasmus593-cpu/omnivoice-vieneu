#!/usr/bin/env python3
"""
Build pipeline for OmniVoice Cloner.
Adapted from V3.4 build_v3_4.py for OmniVoice desktop app.

Usage:
  python build_omnivoice.py                  # Full release build (PyArmor + PyInstaller)
  python build_omnivoice.py --skip-pyarmor   # Debug build (no obfuscation)
  python build_omnivoice.py --skip-smoke-test # Skip post-build smoke test
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

BUILD_TAG_BASE = "V1.1"
SCRIPT_NAME = Path(__file__).name

APP_NAME = "AI86-VoiceCloner"
ENTRYPOINT = BASE_DIR / "main_secure.py"
ICON_ICO = BASE_DIR / "favicon.ico"
ICON_PNG = BASE_DIR / "Applogo.png"
MANIFEST_FILENAME = "RELEASE_MANIFEST.json"

OUTPUT_DIR = BASE_DIR / "dist"
OUTPUT_APP_DIR = OUTPUT_DIR / APP_NAME
OUTPUT_EXE = OUTPUT_APP_DIR / f"{APP_NAME}.exe"
SHA_FILE = OUTPUT_DIR / f"{APP_NAME}.exe.sha256"
MANIFEST_FILE = OUTPUT_DIR / "RELEASE_MANIFEST.json"
SPEC_OUTPUT_DIR = BASE_DIR / "build" / "pyinstaller_spec"

# Mandatory local model bundle for offline distribution
MODEL_BUNDLE_DIR = BASE_DIR / "omnivoice_model"
MODEL_REQUIRED_FILE = MODEL_BUNDLE_DIR / "model.safetensors"


# ==============================================================================
# Local module imports for --hidden-import
# ==============================================================================
LOCAL_MODULE_IMPORTS = [
    "src",
    "src.core",
    "src.core.engine",
    "src.core.audio_utils",
    "src.core.license_client",
    "src.core.license_models",
    "src.core.runtime_guard",
    "src.core._internal_hashes",
    "src.ui",
    "src.ui.app",
    "src.ui.main_window",
    "src.ui.pages",
    "src.ui.pages.tts_studio",
    "src.ui.pages.voice_library",
    "src.ui.pages.batch_process",
    "src.ui.widgets",
    "src.ui.widgets.audio_player",
    "src.ui.widgets.waveform_widget",
    "src.ui.widgets.drop_area",
    "src.ui.widgets.log_panel",
    "src.ui.workers",
    "src.ui.workers.model_loader",
    "src.ui.workers.tts_worker",
    "src.ui.dialogs",
    "src.ui.dialogs.license_dialog",
    "src.ui.dialogs.license_info_dialog",
    "src.ui.dialogs.help_dialog",
    "src.data",
    "src.data.database",
]

EXTRA_HIDDEN_IMPORTS = [
    # Cryptography for license verification
    "cryptography.hazmat.primitives.asymmetric.ed25519",
    "cryptography.hazmat.primitives.ciphers.aead",
    "cryptography.hazmat.primitives.kdf.hkdf",
    "cryptography.hazmat.primitives.hashes",
    "cryptography.hazmat.backends",
    "nacl.signing",
    "nacl.encoding",
    "nacl.exceptions",
    # Audio
    "pydub.audio_segment",
    "pydub.effects",
    "pydub.utils",
    "soundfile",
    # Qt
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtMultimedia",
    # Torch / AI
    "torch",
    "torchaudio",
    "transformers",
    "omnivoice",
    "safetensors",
    "huggingface_hub",
    "tokenizers",
    # VieNeu TTS & SEA G2P
    "vieneu",
    "sea_g2p",
    "vieneu_utils",
    # Misc
    "numpy",
    "sqlite3",
]

COLLECT_ALL_PACKAGES = [
    "torch",
    "torchaudio",
    "transformers",
    "omnivoice",
    "vieneu",
    "sea_g2p",
    "vieneu_utils",
    "imageio_ffmpeg",
    "PySide6",
    "safetensors",
    "huggingface_hub",
    "tokenizers",
    "cryptography",
    "requests",
    "scipy",
]

EXCLUDE_MODULES = [
    "cv2",
    "numba",
    "llvmlite",
    "lxml",
    "matplotlib",
    "pandas",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "tensorboard",
    "triton",
    "apex",
]


# ==============================================================================
# PyArmor targets — security-critical files to obfuscate
# ==============================================================================
_PYARMOR_TARGETS_ALL = [
    # Group 1: Security-critical (MUST obfuscate)
    "main_secure.py",
    "src/core/license_client.py",
    "src/core/runtime_guard.py",
    "src/core/_internal_hashes.py",
    # Group 2: License domain (PyArmor Pro)
    "src/core/license_models.py",
    "src/ui/dialogs/license_dialog.py",
    "src/ui/dialogs/license_info_dialog.py",
]

_PYARMOR_TARGETS_TRIAL = _PYARMOR_TARGETS_ALL[:4]
_PYARMOR_TARGETS = _PYARMOR_TARGETS_TRIAL
_PYARMOR_OUTPUT_DIR = BASE_DIR / "dist_obf"
_PYARMOR_BACKUP_DIR = BASE_DIR / "dist_obf_src_backup"
_PYARMOR_RUNTIME_PKG: str | None = None
_PYARMOR_APPLIED = False
_PRESERVE_GENERATED_HASHES = False


# ==============================================================================
# Utility functions
# ==============================================================================
def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    print(f"[RUN] {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, check=True, env=env)


def run_capture(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    print(f"[RUN] {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def get_hidden_imports() -> list[str]:
    return unique(LOCAL_MODULE_IMPORTS + EXTRA_HIDDEN_IMPORTS)


def get_excluded_modules() -> list[str]:
    return unique(EXCLUDE_MODULES)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def _get_pyarmor_cmd() -> list[str] | None:
    candidates: list[list[str]] = [
        ["pyarmor"],
        [sys.executable, "-m", "pyarmor"],
        [sys.executable, "-m", "pyarmor.cli"],
    ]
    for candidate in candidates:
        try:
            cp = run_capture(candidate + ["--version"])
            out = (cp.stdout + cp.stderr).strip()
            if out:
                print(f"[OK] Found PyArmor via: {' '.join(candidate)}")
                print(f"[INFO] PyArmor version: {out.splitlines()[0]}")
            else:
                print(f"[OK] Found PyArmor via: {' '.join(candidate)}")
            return candidate
        except Exception:
            continue
    return None


def _get_pyarmor_targets() -> list[str]:
    pyarmor_cmd = _get_pyarmor_cmd()
    if pyarmor_cmd is None:
        return list(_PYARMOR_TARGETS_TRIAL)

    try:
        cp = run_capture(pyarmor_cmd + ["--version"])
        out = (cp.stdout + cp.stderr).lower()
        if "trial" in out:
            print("[INFO] PyArmor Trial detected: obfuscating 4 security-critical files")
            return list(_PYARMOR_TARGETS_TRIAL)
        print("[INFO] PyArmor Pro/Full detected: obfuscating full license domain")
        return list(_PYARMOR_TARGETS_ALL)
    except Exception:
        return list(_PYARMOR_TARGETS_TRIAL)


def backup_source_files() -> None:
    return


def restore_source_files() -> None:
    return

    global _PYARMOR_RUNTIME_PKG
    if _PYARMOR_RUNTIME_PKG:
        runtime_pkg = _PYARMOR_RUNTIME_PKG
        runtime_dir = BASE_DIR / runtime_pkg
        if runtime_dir.exists():
            shutil.rmtree(runtime_dir, ignore_errors=True)
            print(f"[INFO] Removed temporary runtime package: {runtime_pkg}")
        if runtime_pkg in COLLECT_ALL_PACKAGES:
            COLLECT_ALL_PACKAGES.remove(runtime_pkg)
            print(f"[INFO] Removed runtime collect-all: {runtime_pkg}")
        _PYARMOR_RUNTIME_PKG = None


def _resolve_obfuscated_file(rel_target: str) -> Path:
    rel_path = Path(rel_target)
    candidates = [
        _PYARMOR_OUTPUT_DIR / rel_path,
        _PYARMOR_OUTPUT_DIR / rel_path.name,
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c

    # Fallback: find by filename inside output tree
    matches = list(_PYARMOR_OUTPUT_DIR.rglob(rel_path.name))
    for m in matches:
        if m.is_file():
            return m

    fail(f"Obfuscated file not found for target: {rel_target}")
    raise AssertionError("unreachable")


def run_pyarmor_obfuscation(required: bool = True) -> bool:
    global _PYARMOR_RUNTIME_PKG, _PYARMOR_APPLIED

    pyarmor_cmd = _get_pyarmor_cmd()
    if pyarmor_cmd is None:
        if required:
            fail("PyArmor is required but not installed/found")
        print("[WARN] PyArmor not found, skipping obfuscation")
        return False

    if _PYARMOR_OUTPUT_DIR.exists():
        shutil.rmtree(_PYARMOR_OUTPUT_DIR)
    _PYARMOR_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    targets = [str(BASE_DIR / rel) for rel in _PYARMOR_TARGETS]
    cmd = pyarmor_cmd + ["gen", "--output", str(_PYARMOR_OUTPUT_DIR)] + targets
    run(cmd)

    # Overwrite source files with obfuscated versions
    for rel in _PYARMOR_TARGETS:
        obf = _resolve_obfuscated_file(rel)
        dst = BASE_DIR / rel
        shutil.copy2(obf, dst)
        print(f"[OK] Obfuscated: {rel}")

    # Locate and copy pyarmor runtime package
    runtime_dirs = [
        p for p in _PYARMOR_OUTPUT_DIR.rglob("pyarmor_runtime_*")
        if p.is_dir() and p.name.startswith("pyarmor_runtime_")
    ]
    if not runtime_dirs:
        fail("PyArmor runtime package (pyarmor_runtime_*) not found in output")

    runtime_src = runtime_dirs[0]
    runtime_pkg = runtime_src.name
    runtime_dst = BASE_DIR / runtime_pkg
    if runtime_dst.exists():
        shutil.rmtree(runtime_dst)
    shutil.copytree(runtime_src, runtime_dst)
    print(f"[OK] Copied runtime package: {runtime_pkg}")

    try:
        importlib.import_module(runtime_pkg)
    except Exception as exc:
        print(
            f"[WARN] PyArmor runtime import blocked ({runtime_pkg}): {exc}. "
            "Falling back to non-obfuscated build."
        )
        shutil.rmtree(runtime_dst, ignore_errors=True)
        return False

    _PYARMOR_RUNTIME_PKG = runtime_pkg
    if runtime_pkg not in COLLECT_ALL_PACKAGES:
        COLLECT_ALL_PACKAGES.append(runtime_pkg)

    _PYARMOR_APPLIED = True
    return True


def verify_local_model_bundle() -> Path:
    if not MODEL_BUNDLE_DIR.exists() or not MODEL_BUNDLE_DIR.is_dir():
        fail(
            "Missing local model bundle directory: "
            f"{MODEL_BUNDLE_DIR}. Expected offline model in ./omnivoice_model"
        )

    required_model_files = [
        MODEL_BUNDLE_DIR / "model.safetensors",
        MODEL_BUNDLE_DIR / "config.json",
        MODEL_BUNDLE_DIR / "tokenizer.json",
        MODEL_BUNDLE_DIR / "audio_tokenizer" / "model.safetensors",
    ]
    missing = [str(p) for p in required_model_files if not p.exists()]
    if missing:
        fail(
            "Local model bundle missing required files before packaging:\n - "
            + "\n - ".join(missing)
        )

    print(f"[OK] Verified local model bundle: {MODEL_BUNDLE_DIR}")
    return MODEL_BUNDLE_DIR


def guard_checks(skip_pyarmor: bool = False) -> None:
    if not ENTRYPOINT.exists():
        fail(f"Missing secure entrypoint: {ENTRYPOINT}")

    content = ENTRYPOINT.read_text(encoding="utf-8", errors="ignore")
    required_markers = [
        "IsDebuggerPresent",
        "_native_anti_debug",
        "NtQueryInformationProcess",
        "_verify_internal_integrity",
    ]
    missing = [m for m in required_markers if m not in content]
    if missing:
        fail(f"main_secure.py is missing required security markers: {missing}")

    hashes_file = BASE_DIR / "src" / "core" / "_internal_hashes.py"
    if not hashes_file.exists():
        fail("Missing src/core/_internal_hashes.py")

    if not skip_pyarmor:
        # PyArmor is now removed from the build process
        pass


def check_torch_cuda() -> None:
    try:
        import torch
    except Exception as exc:
        fail(f"Cannot import torch: {exc}")

    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        vram = round(getattr(props, "total_memory", 0) / (1024**3), 2)
        print(f"[OK] CUDA available: {name} ({vram} GB)")
    else:
        print("[WARN] CUDA not available. Build can continue, runtime will be CPU-only.")


def ensure_build_dependencies() -> None:
    modules = [
        "PyInstaller",
        "torch",
        "torchaudio",
        "transformers",
        "omnivoice",
        "PySide6",
        "cryptography",
        "nacl",
        "pydub",
        "soundfile",
    ]
    missing: list[str] = []
    for mod in modules:
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(mod)

    if missing:
        fail(
            "Missing build dependencies: "
            + ", ".join(missing)
            + "\nInstall via pip before building."
        )

    if not ENTRYPOINT.exists():
        fail(f"Missing entrypoint: {ENTRYPOINT}")
    if not ICON_ICO.exists():
        fail(f"Missing icon: {ICON_ICO}")
    if not ICON_PNG.exists():
        fail(f"Missing logo: {ICON_PNG}")


def clean_output() -> None:
    targets = [
        BASE_DIR / "build",
        BASE_DIR / "dist",
        BASE_DIR / "dist_obf",
    ]
    for p in targets:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            print(f"[CLEAN] Removed directory: {p}")

    for spec in BASE_DIR.glob("*.spec"):
        spec.unlink(missing_ok=True)
        print(f"[CLEAN] Removed spec: {spec}")


def get_add_data_args() -> list[str]:
    style_qss = BASE_DIR / "src" / "resources" / "style.qss"
    if not style_qss.exists():
        fail(f"Missing stylesheet: {style_qss}")

    model_bundle = verify_local_model_bundle()

    # Voice library (pre-built sample voices)
    voice_lib = BASE_DIR / "omnivoice_voice_library"
    add_voice_lib = []
    if voice_lib.exists() and (voice_lib / "voices.json").exists():
        add_voice_lib = ["--add-data", f"{voice_lib};omnivoice_voice_library"]
        print(f"[OK] Including voice library: {voice_lib}")
    else:
        print("[WARN] Voice library sample data not found, skipping (warning-only)")

    # Optional pre-generated prompt cache seed
    prompt_cache_seed = BASE_DIR / "omnivoice_prompt_cache"
    add_prompt_cache_seed = []
    if prompt_cache_seed.exists() and prompt_cache_seed.is_dir():
        add_prompt_cache_seed = ["--add-data", f"{prompt_cache_seed};omnivoice_prompt_cache"]
        print(f"[OK] Including prompt cache seed: {prompt_cache_seed}")
    else:
        print("[WARN] Prompt cache seed not found, skipping (warning-only)")

    return [
        "--add-data", f"{ICON_PNG};.",
        "--add-data", f"{ICON_ICO};.",
        "--add-data", f"{style_qss};src/resources",
        "--add-data", f"{model_bundle};omnivoice_model",
    ] + add_voice_lib + add_prompt_cache_seed


_DEBUG_BUILD = False


def build_with_pyinstaller() -> str:
    SPEC_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--name",
        APP_NAME,
        "--icon",
        str(ICON_ICO),
        "--specpath",
        str(SPEC_OUTPUT_DIR),
    ]

    if _DEBUG_BUILD:
        cmd += ["--log-level", "DEBUG"]

    for item in get_hidden_imports():
        cmd += ["--hidden-import", item]

    for item in unique(COLLECT_ALL_PACKAGES):
        cmd += ["--collect-all", item]

    for item in get_excluded_modules():
        cmd += ["--exclude-module", item]

    cmd += get_add_data_args()
    cmd.append(str(ENTRYPOINT))

    run(cmd)

    if not OUTPUT_APP_DIR.exists():
        fail(f"PyInstaller output directory not found: {OUTPUT_APP_DIR}")
    if not OUTPUT_EXE.exists():
        fail(f"PyInstaller output exe not found: {OUTPUT_EXE}")

    shutil.copy2(ICON_PNG, OUTPUT_APP_DIR / ICON_PNG.name)
    shutil.copy2(ICON_ICO, OUTPUT_APP_DIR / ICON_ICO.name)

    print(f"[OK] PyInstaller build complete: {OUTPUT_EXE}")
    return str(OUTPUT_EXE)


_INTERNAL_CRITICAL_FILES = [
    # Crypto engine — patch = break all signature verification
    "cryptography/hazmat/bindings/_rust.pyd",
    # Ed25519 signature verification — patch = forge any license token
    "nacl/_sodium.pyd",
    # PySide6 core — patch = bypass license dialog UI
    "PySide6/QtCore.pyd",
    "PySide6/QtWidgets.pyd",
]

# Critical files resolved dynamically at build time (ABI filename can change)
_INTERNAL_CRITICAL_GLOBS = [
    # CFFI backend — used by cryptography, patch = hijack crypto calls
    "_cffi_backend*.pyd",
]

# Additional optional files resolved dynamically at build time (e.g. pyarmor_runtime)
_INTERNAL_DYNAMIC_PATTERNS = [
    "pyarmor_runtime_*/pyarmor_runtime.pyd",
]


def generate_internal_hashes() -> None:
    internal_dir = OUTPUT_APP_DIR / "_internal"
    if not internal_dir.exists():
        fail(f"_internal directory not found: {internal_dir}")

    hashes: dict[str, str] = {}
    missing: list[str] = []

    for rel in _INTERNAL_CRITICAL_FILES:
        p = internal_dir / rel
        if not p.exists():
            missing.append(rel)
            continue
        hashes[rel] = sha256_file(p)

    # Resolve critical ABI-dependent files (must exist at least one match)
    for pattern in _INTERNAL_CRITICAL_GLOBS:
        matches = [m for m in internal_dir.glob(pattern) if m.is_file()]
        if not matches:
            missing.append(pattern)
            continue
        for m in sorted(matches):
            rel = m.relative_to(internal_dir).as_posix()
            hashes[rel] = sha256_file(m)
            print(f"[OK] Dynamic critical hash: {rel}")

    # Resolve optional dynamic patterns (e.g. pyarmor_runtime_XXXXXX/pyarmor_runtime.pyd)
    for pattern in _INTERNAL_DYNAMIC_PATTERNS:
        matches = [m for m in internal_dir.glob(pattern) if m.is_file()]
        for m in sorted(matches):
            rel = m.relative_to(internal_dir).as_posix()
            hashes[rel] = sha256_file(m)
            print(f"[OK] Dynamic hash: {rel}")

    if missing:
        fail("Missing critical _internal files for hashing:\n - " + "\n - ".join(missing))

    out_file = BASE_DIR / "src" / "core" / "_internal_hashes.py"
    lines = [
        '"""',
        "AUTO-GENERATED by build_omnivoice.py — DO NOT EDIT MANUALLY.",
        "SHA-256 hashes of critical files in _internal/.",
        "Verified by _verify_internal_integrity() in main_secure.py.",
        '"""',
        "HASHES: dict[str, str] = {",
    ]
    for rel, digest in sorted(hashes.items()):
        lines.append(f'    "{rel}": "{digest}",')
    lines.append("}")
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[OK] Generated internal hashes: {out_file}")


def _next_build_tag() -> str:
    now = datetime.now()
    date_part = now.strftime("%d%m%Y")
    time_part = now.strftime("%H%M")

    max_build = 0
    pattern = rf"^{re.escape(BUILD_TAG_BASE)}\.(\d+)-\d{{8}}(?:-\d{{4}})?$"

    for manifest_path in sorted(BASE_DIR.glob("dist*/RELEASE_MANIFEST.json")):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            tag = str(data.get("build_tag", "")).strip()
            match = re.match(pattern, tag)
            if match:
                max_build = max(max_build, int(match.group(1)))
        except Exception:
            continue

    return f"{BUILD_TAG_BASE}.{max_build + 1}-{date_part}-{time_part}"


def write_release_artifacts(build_tag: str) -> None:
    if not OUTPUT_EXE.exists():
        fail(f"Cannot write artifacts, exe not found: {OUTPUT_EXE}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    exe_sha = sha256_file(OUTPUT_EXE)
    exe_size = OUTPUT_EXE.stat().st_size
    bundle_size = dir_size(OUTPUT_APP_DIR)

    SHA_FILE.write_text(f"{exe_sha}  {OUTPUT_EXE.name}\n", encoding="utf-8")

    manifest = {
        "app_name": APP_NAME,
        "build_tag": build_tag,
        "build_script": SCRIPT_NAME,
        "build_time": datetime.now(timezone.utc).isoformat(),
        "exe_path": str(OUTPUT_EXE),
        "exe_size": exe_size,
        "bundle_size": bundle_size,
        "sha256": exe_sha,
        "pyarmor_enabled": _PYARMOR_APPLIED,
        "pyarmor_obfuscated": list(_PYARMOR_TARGETS),
        "pyarmor_runtime": _PYARMOR_RUNTIME_PKG,
        "model_bundle_path": str(MODEL_BUNDLE_DIR),
        "model_bundle_required_file": str(MODEL_REQUIRED_FILE),
        "offline_policy": {
            "frozen_strict_local_only": True,
            "optional_warning_only": [
                "omnivoice_prompt_cache",
                "omnivoice_voice_library",
            ],
        },
    }

    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    MANIFEST_FILE.write_text(manifest_text, encoding="utf-8")
    (OUTPUT_APP_DIR / MANIFEST_FILENAME).write_text(manifest_text, encoding="utf-8")

    print(f"[OK] Wrote release artifacts: {SHA_FILE.name}, {MANIFEST_FILE.name}")


def verify_release_artifacts() -> None:
    if not SHA_FILE.exists():
        fail(f"Missing SHA file: {SHA_FILE}")
    if not MANIFEST_FILE.exists():
        fail(f"Missing manifest file: {MANIFEST_FILE}")

    actual_sha = sha256_file(OUTPUT_EXE)

    sha_line = SHA_FILE.read_text(encoding="utf-8").strip()
    if not sha_line:
        fail("SHA file is empty")
    sha_from_file = sha_line.split()[0]
    if sha_from_file != actual_sha:
        fail("SHA mismatch between .sha256 file and built exe")

    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    manifest_sha = manifest.get("sha256", "")
    if manifest_sha != actual_sha:
        fail("SHA mismatch between RELEASE_MANIFEST.json and built exe")

    print("[OK] Release artifacts verified")


def run_exe_smoke_test() -> None:
    if not OUTPUT_EXE.exists():
        fail(f"Smoke test failed: exe not found: {OUTPUT_EXE}")

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"

    cmd = [str(OUTPUT_EXE), "--smoke-test"]
    print(f"[RUN] {' '.join(cmd)}")
    cp = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    if cp.stdout.strip():
        print(cp.stdout.strip())
    if cp.stderr.strip():
        print(cp.stderr.strip())

    if cp.returncode != 0:
        fail(f"Smoke test failed with exit code {cp.returncode}")

    print("[OK] Smoke test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build OmniVoice Cloner release package")
    parser.add_argument(
        "--skip-pyarmor",
        action="store_true",
        help="Skip PyArmor obfuscation (debug build only)",
    )
    parser.add_argument(
        "--skip-smoke-test",
        action="store_true",
        help="Skip running post-build smoke test",
    )
    parser.add_argument(
        "--debug-build",
        action="store_true",
        help="Enable debug-level PyInstaller output",
    )
    return parser.parse_args()


def main() -> int:
    global _DEBUG_BUILD, _PRESERVE_GENERATED_HASHES

    args = parse_args()
    _DEBUG_BUILD = bool(args.debug_build)
    build_tag = _next_build_tag()

    print(f"=== {APP_NAME} Build Pipeline ({build_tag}) ===")
    print(f"[INFO] Base dir: {BASE_DIR}")

    source_backed_up = False
    pyarmor_applied = False

    try:
        ensure_build_dependencies()
        check_torch_cuda()
        guard_checks(skip_pyarmor=args.skip_pyarmor)

        # PyArmor has been removed from the build process per user request
        print("[INFO] PyArmor obfuscation is permanently disabled.")

        clean_output()

        # === 2-PASS BUILD ===
        # Pass 1: Build to discover actual file hashes in _internal/
        print("[INFO] === Pass 1: Build to generate integrity hashes ===")
        build_with_pyinstaller()
        generate_internal_hashes()

        # Pass 2: Re-build with correct hashes baked into _internal_hashes.py
        # (The PYZ archive now includes the populated HASHES dict)
        print("[INFO] === Pass 2: Re-build with integrity hashes ===")
        build_with_pyinstaller()

        _PRESERVE_GENERATED_HASHES = True
        write_release_artifacts(build_tag)
        verify_release_artifacts()

        if not args.skip_smoke_test:
            run_exe_smoke_test()
        else:
            print("[INFO] --skip-smoke-test enabled")

        print("[OK] Build completed successfully")
        return 0
    except subprocess.CalledProcessError as exc:
        fail(f"Command failed with code {exc.returncode}: {exc.cmd}")
    except Exception as exc:
        fail(f"Unhandled error: {exc}")
    finally:
        if source_backed_up:
            restore_source_files()
        elif pyarmor_applied:
            # Defensive fallback, should not happen because pyarmor_applied implies backup
            restore_source_files()
        _PRESERVE_GENERATED_HASHES = False


if __name__ == "__main__":
    raise SystemExit(main())
