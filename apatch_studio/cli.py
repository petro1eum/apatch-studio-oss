"""Command-line launcher for APatch Studio OSS."""

from __future__ import annotations

import argparse
import os
import socket
import threading
import webbrowser
from pathlib import Path

import uvicorn

from apatch_studio.app import create_app
from apatch_studio.edition import StudioEdition
from apatch_studio.endpoint_enrollment import (
    adopt_identity,
    apply_stored_identity,
    enroll_machine,
    enrollment_readiness,
    name_this_machine,
)
from apatch_studio.endpoint_identity import endpoint_identity_status
from apatch_studio.execution_intents import ExecutionIntentTrust
from apatch_studio.run_store import default_state_root
from apatch_studio.runtime_requirements import probe_runtime_requirements, runtime_banner_lines
from apatch_studio.security import is_loopback_host


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apatch-studio",
        description="Local governed workspace for APatch and TrustChain Cowork.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the local Studio workspace")
    serve.add_argument("--workspace", required=True, help="Local Git workspace")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-open", action="store_true")
    serve.add_argument("--log-level", default="warning")
    serve.add_argument(
        "--execution-intent-trust-file",
        default=os.environ.get("APATCH_STUDIO_EXECUTION_INTENT_TRUST_FILE"),
        help="Public authority pins for signed tasks received from Cowork",
    )

    sub.add_parser(
        "name-this-machine",
        help="Give this machine a local self-asserted name",
    )

    enrol = sub.add_parser("enroll", help="Give this machine a verifiable identity")
    enrol.add_argument("--platform", help="Organization address, https")
    enrol.add_argument(
        "--invitation",
        help="Enrollment invitation (visible in shell history; prefer --invitation-file)",
    )
    enrol.add_argument("--invitation-file", help="File holding the enrollment invitation")
    enrol.add_argument("--machine-name", default=None, help="Name for this machine")
    enrol.add_argument("--existing-key", help="Adopt a key this machine already holds")
    enrol.add_argument("--existing-certificate", help="Certificate for the adopted key")
    enrol.add_argument("--root-ca", help="Issuing root certificate for offline verification")
    enrol.add_argument("--intermediate", help="Issuing intermediate certificate")
    return parser


def _loopback_socket_config(host: str, port: int) -> tuple[int, tuple[str, int], str]:
    bind_host = host.strip()
    if bind_host.startswith("[") and bind_host.endswith("]"):
        bind_host = bind_host[1:-1]
    if not is_loopback_host(bind_host):
        raise ValueError("APatch Studio OSS only binds to a loopback host")
    family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
    display_host = f"[{bind_host}]" if family == socket.AF_INET6 else bind_host
    return family, (bind_host, port), display_host


def serve(args: argparse.Namespace) -> int:
    try:
        family, address, display_host = _loopback_socket_config(args.host, args.port)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    workspace = Path(args.workspace).expanduser().resolve()
    apply_stored_identity(default_state_root())
    try:
        trust = (
            ExecutionIntentTrust.from_path(args.execution_intent_trust_file)
            if args.execution_intent_trust_file
            else None
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    app = create_app(
        str(workspace),
        edition=StudioEdition.OSS,
        execution_intent_trust=trust,
    )

    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(address)
    sock.listen(128)
    port = int(sock.getsockname()[1])
    url = f"http://{display_host}:{port}/"
    print(f"APatch Studio OSS: {url}", flush=True)
    print(f"Workspace: {workspace.name}", flush=True)
    for line in runtime_banner_lines(probe_runtime_requirements()):
        print(line, flush=True)
    identity = endpoint_identity_status(str(workspace))
    print(f"Machine identity: {identity['headline']}", flush=True)
    if not identity["enrolled"]:
        print(f"  {identity['next_step']}", flush=True)
    if not args.no_open:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()

    config = uvicorn.Config(app, log_level=args.log_level, access_log=False)
    uvicorn.Server(config).run(sockets=[sock])
    return 0


def enroll(args: argparse.Namespace) -> int:
    """Enroll this machine, once, from the operator's terminal."""

    if args.existing_key or args.existing_certificate:
        if not (args.existing_key and args.existing_certificate and args.machine_name):
            raise SystemExit(
                "adopting an identity needs --existing-key, --existing-certificate "
                "and --machine-name"
            )
        try:
            adopted = adopt_identity(
                state_root=default_state_root(),
                machine_name=args.machine_name,
                key_path=args.existing_key,
                certificate_path=args.existing_certificate,
                platform_url=args.platform,
                root_ca=args.root_ca,
                intermediate=args.intermediate,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(adopted["headline"], flush=True)
        print("  " + adopted["explanation"], flush=True)
        if adopted["next_step"] != "Nothing to do.":
            print("  " + adopted["next_step"], flush=True)
        return 0 if adopted["enrolled"] else 1

    readiness = enrollment_readiness()
    if not readiness["ready"]:
        print(readiness["headline"], flush=True)
        print("  " + readiness["explanation"], flush=True)
        print("  " + readiness["next_step"], flush=True)
        return 1
    if bool(args.invitation) == bool(args.invitation_file):
        raise SystemExit("pass exactly one of --invitation or --invitation-file")
    if args.invitation_file:
        try:
            invitation = Path(args.invitation_file).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(f"could not read the invitation file: {exc}") from exc
    else:
        invitation = args.invitation
    try:
        result = enroll_machine(
            state_root=default_state_root(),
            invitation=invitation,
            platform_url=args.platform,
            machine_name=args.machine_name,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(result["headline"], flush=True)
    print("  " + result["explanation"], flush=True)
    if result["next_step"] != "Nothing to do.":
        print("  " + result["next_step"], flush=True)
    return 0 if result["enrolled"] else 1


def name_machine(_args: argparse.Namespace) -> int:
    """Name this machine locally, while stating the limit of that claim."""

    try:
        record = name_this_machine(state_root=default_state_root())
    except ValueError as exc:
        print(str(exc), flush=True)
        return 1
    print(f"This machine is now called {record['machine_name']}.", flush=True)
    print(
        "  The name is this machine's own word. Nobody outside it vouched for it, "
        "so it says who acted in your workspaces and proves nothing to anyone else.",
        flush=True,
    )
    print(
        "  Enroll with your organization when you have one, for a name a stranger can check.",
        flush=True,
    )
    return 0


def main() -> int:
    args = _parser().parse_args()
    if args.command == "serve":
        return serve(args)
    if args.command == "enroll":
        return enroll(args)
    if args.command == "name-this-machine":
        return name_machine(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
