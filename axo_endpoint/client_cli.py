from __future__ import annotations

import argparse
import importlib
import json
import sys


def _print_result(result) -> None:
    status = "OK" if result.ok else "ERROR"
    print(f"status : {status}")
    if not result.ok:
        print(f"error  : {result.error}")
    if result.metadata:
        print(f"meta   : {json.dumps(result.metadata, indent=2, default=str)}")


def _client(args) -> "AxoEndpointClient":
    from axo_shared.client import AxoEndpointClient
    return AxoEndpointClient(args.address, timeout_ms=args.timeout * 1000)


def cmd_ping(args) -> None:
    with _client(args) as c:
        _print_result(c.ping())


def cmd_register(args) -> None:
    module_path, fn_name = args.fn.rsplit(":", 1)
    mod = importlib.import_module(module_path)
    fn = getattr(mod, fn_name)
    runtime_spec = None
    if args.runtime == "container":
        runtime_spec = {
            "type": "container",
            "python_version": args.python_version,
            "requirements": [r.strip() for r in args.requirements.split(",") if r.strip()]
            if args.requirements else [],
        }
    with _client(args) as c:
        _print_result(c.register_function(
            args.user_id, args.virtual_environment_id, args.name, fn=fn, runtime_spec=runtime_spec,
        ))


def cmd_delete_function(args) -> None:
    with _client(args) as c:
        _print_result(c.delete_function(args.user_id, args.virtual_environment_id, args.name, args.version))


def cmd_update_function(args) -> None:
    env_vars = json.loads(args.env_vars) if args.env_vars else None
    params_schema = json.loads(args.params_schema) if args.params_schema else None
    with _client(args) as c:
        _print_result(c.update_function(
            args.user_id, args.virtual_environment_id, args.name, args.version,
            params_schema=params_schema, env_vars=env_vars,
        ))


def cmd_submit(args) -> None:
    params = json.loads(args.params) if args.params else {}
    with _client(args) as c:
        result = c.submit_job(args.user_id, args.virtual_environment_id, args.name, args.version, params)
        _print_result(result)
        if result.ok:
            print(f"job_id : {result.metadata.get('job_id')}")


def cmd_result(args) -> None:
    with _client(args) as c:
        _print_result(c.get_job_result(args.job_id))


def cmd_register_data(args) -> None:
    with _client(args) as c:
        _print_result(c.upload_data(
            args.name, args.version, args.file, format=args.format, kind=args.kind,
            chunk_bytes=args.chunk_bytes, resume=not args.no_resume,
        ))


def cmd_data_info(args) -> None:
    with _client(args) as c:
        _print_result(c.data_info(args.name, args.version))


def cmd_activity(args) -> None:
    with _client(args) as c:
        _print_result(c.list_activity(function_id=args.function_id, limit=args.limit))


def cmd_run(args) -> None:
    from axo_shared.client import AxoClientTimeout
    params = json.loads(args.params) if args.params else {}
    with _client(args) as c:
        try:
            result = c.run(
                args.user_id,
                args.virtual_environment_id,
                args.name,
                args.version,
                params,
                poll_interval=args.poll_interval,
                timeout=args.run_timeout,
            )
            _print_result(result)
        except AxoClientTimeout as exc:
            print(f"TIMEOUT: {exc}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="axec",
        description="axo-endpoint-client — send commands to an axo_endpoint node",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        metavar="SECONDS",
        help="ZMQ receive timeout in seconds (default: 5)",
    )
    parser.add_argument(
        "--user-id",
        default="local",
        help="Caller identity used to derive function_id (default: local) -- "
             "this direct-node path does no real auth, it's just an identifier",
    )
    parser.add_argument(
        "--virtual-environment-id",
        default="default",
        dest="virtual_environment_id",
        help="Workspace identity used to derive function_id (default: default)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ping
    p_ping = sub.add_parser("ping", help="Check node liveness")
    p_ping.add_argument("address", help="Node address, e.g. tcp://localhost:5555")
    p_ping.set_defaults(func=cmd_ping)

    # register
    p_reg = sub.add_parser("register", help="Register a function on the node")
    p_reg.add_argument("address", help="Node address")
    p_reg.add_argument("fn", help="Python dotted path to the function: module:fn_name")
    p_reg.add_argument("--name", required=True, help="Function name to register as")
    p_reg.add_argument("--runtime", choices=["process", "container"], default="process",
                       help="Execution runtime (default: process)")
    p_reg.add_argument("--python-version", default="3.11", metavar="VERSION",
                       help="Python version for container runtime (default: 3.11)")
    p_reg.add_argument("--requirements", default=None, metavar="PKGS",
                       help="Comma-separated pip requirements for container runtime")
    p_reg.set_defaults(func=cmd_register)

    # delete-function
    p_del = sub.add_parser("delete-function", help="Delete a registered function's code and metadata")
    p_del.add_argument("address", help="Node address")
    p_del.add_argument("name", help="Registered function name")
    p_del.add_argument("--version", type=int, default=0, help="Function version (default: 0)")
    p_del.set_defaults(func=cmd_delete_function)

    # update-function
    p_upd = sub.add_parser("update-function", help="Merge new env_vars/params_schema into a registered function")
    p_upd.add_argument("address", help="Node address")
    p_upd.add_argument("name", help="Registered function name")
    p_upd.add_argument("--version", type=int, default=0, help="Function version (default: 0)")
    p_upd.add_argument("--env-vars", default=None, metavar="JSON", dest="env_vars",
                        help='Env vars to merge in, as a JSON object, e.g. \'{"A": "1"}\'')
    p_upd.add_argument("--params-schema", default=None, metavar="JSON", dest="params_schema",
                        help="New params_schema entries to append, as a JSON array")
    p_upd.set_defaults(func=cmd_update_function)

    # submit
    p_sub = sub.add_parser("submit", help="Submit a job and return its job_id immediately")
    p_sub.add_argument("address", help="Node address")
    p_sub.add_argument("name", help="Registered function name")
    p_sub.add_argument("--version", type=int, default=0, help="Function version (default: 0)")
    p_sub.add_argument("--params", default=None, metavar="JSON", help="Job params as JSON object")
    p_sub.set_defaults(func=cmd_submit)

    # result
    p_res = sub.add_parser("result", help="Poll the result of a job")
    p_res.add_argument("address", help="Node address")
    p_res.add_argument("job_id", help="Job ID returned by submit")
    p_res.set_defaults(func=cmd_result)

    # register-data
    from axo_endpoint.dataio import DEFAULT_CHUNK_BYTES
    p_data_reg = sub.add_parser("register-data", help="Register and chunk-upload a file's data")
    p_data_reg.add_argument("address", help="Node address")
    p_data_reg.add_argument("name", help="Data name to register as")
    p_data_reg.add_argument("version", type=int, help="Data version")
    p_data_reg.add_argument("file", help="Path to the file to upload")
    p_data_reg.add_argument("--format", default="raw", help="dataio format (raw/pickle/csv/npy, default: raw)")
    p_data_reg.add_argument("--kind", default="fs", help="Storage backend kind (default: fs)")
    p_data_reg.add_argument("--chunk-bytes", type=int, default=DEFAULT_CHUNK_BYTES, dest="chunk_bytes",
                             metavar="BYTES", help=f"Chunk size in bytes (default: {DEFAULT_CHUNK_BYTES})")
    p_data_reg.add_argument("--no-resume", action="store_true",
                             help="Always re-upload every chunk instead of skipping already-present ones")
    p_data_reg.set_defaults(func=cmd_register_data)

    # data-info
    p_data_info = sub.add_parser("data-info", help="Query registered data status/replication info")
    p_data_info.add_argument("address", help="Node address")
    p_data_info.add_argument("name", help="Data name")
    p_data_info.add_argument("version", type=int, help="Data version")
    p_data_info.set_defaults(func=cmd_data_info)

    # activity
    p_activity = sub.add_parser("activity", help="List recorded job/container activity for this node")
    p_activity.add_argument("address", help="Node address")
    p_activity.add_argument("--function-id", default=None, dest="function_id", metavar="NAME",
                             help="Filter to one function's activity (default: all)")
    p_activity.add_argument("--limit", type=int, default=100, help="Max records to return (default: 100)")
    p_activity.set_defaults(func=cmd_activity)

    # run
    p_run = sub.add_parser("run", help="Submit a job and wait for it to finish")
    p_run.add_argument("address", help="Node address")
    p_run.add_argument("name", help="Registered function name")
    p_run.add_argument("--version", type=int, default=0, help="Function version (default: 0)")
    p_run.add_argument("--params", default=None, metavar="JSON", help="Job params as JSON object")
    p_run.add_argument("--poll-interval", type=float, default=0.5, metavar="SECONDS",
                       help="How often to poll for the result (default: 0.5)")
    p_run.add_argument("--run-timeout", type=float, default=30.0, metavar="SECONDS",
                       help="Max seconds to wait for the job to complete (default: 30)")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
