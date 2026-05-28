"""生成打包所需的默认资源。"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tuv_tools.config import AppSettings


DEFAULT_BASE_URL = "http://124.220.92.76:8080"
DEFAULT_CA_FILE_NAME = "default-ca.pem"
DEFAULT_TOKEN_CACHE_FILE = ".token_cache"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare packaging defaults for TUV Tools.")
    parser.add_argument(
        "--base-url",
        default="",
        help=f"Default backend URL to seed. Defaults to current config or {DEFAULT_BASE_URL}.",
    )
    parser.add_argument(
        "--cert",
        default="",
        help="Source CA certificate path. Defaults to the currently configured CA certificate.",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Output directory for generated defaults. Defaults to resources/defaults under the project root.",
    )
    return parser


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = _build_arg_parser().parse_args()
    settings = AppSettings()
    config = settings.load_api_config()
    if config is None:
        raise RuntimeError("Current API config is missing; cannot prepare packaging defaults.")

    base_url = (args.base_url or config.base_url or DEFAULT_BASE_URL).strip()
    if not base_url:
        raise RuntimeError("Default base_url is empty; provide --base-url or configure the current project first.")

    cert_source_text = (args.cert or config.ca_cert_file).strip()
    if not cert_source_text:
        raise RuntimeError("No CA certificate configured; provide --cert or configure the current project first.")

    cert_source = Path(cert_source_text).expanduser().resolve()
    if not cert_source.exists():
        raise FileNotFoundError(f"CA certificate file not found: {cert_source}")

    rsa_private_key = config.rsa_private_key.strip()
    if not rsa_private_key:
        raise RuntimeError("Current RSA private key is empty; cannot prepare packaging defaults.")

    clean_rules = settings._db.load_clean_rules()
    if not clean_rules:
        raise RuntimeError("Current clean rules are empty; cannot prepare packaging defaults.")

    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir.strip()
        else (settings.get_resources_dir() / "defaults").resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        output_dir / "api_config.json",
        {
            "base_url": base_url,
            "username": "",
            "password": "",
            "request_timeout": config.request_timeout,
            "token_idle_timeout": config.token_idle_timeout,
            "token_cache_file": DEFAULT_TOKEN_CACHE_FILE,
            "ca_cert_file": DEFAULT_CA_FILE_NAME,
        },
    )
    _write_json(output_dir / "inline_clean_rules.json", {"inline_clean_rules": clean_rules})
    (output_dir / "rsa_private.key").write_text(rsa_private_key, encoding="utf-8")
    shutil.copy2(cert_source, output_dir / DEFAULT_CA_FILE_NAME)

    print(f"Prepared packaging defaults in: {output_dir}")
    print(f"- api_config.json (base_url={base_url})")
    print(f"- inline_clean_rules.json ({len(clean_rules)} rules)")
    print(f"- rsa_private.key ({len(rsa_private_key)} chars)")
    print(f"- {DEFAULT_CA_FILE_NAME} <- {cert_source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
