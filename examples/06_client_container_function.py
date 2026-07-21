"""Run against a live node, e.g.:  ./axo_endpoint.sh --env-file .env.dev
Then:  python examples/06_client_container_function.py

Requires Docker running and the `axo-net` network to exist:
  docker network create axo-net

Uses --python-version 3.10 rather than the RuntimeSpec default (3.11) --
this project's pinned pandas==1.4.3 has no prebuilt wheel for 3.11, which
fails the runner image build from source.
"""
from axo_shared.client import AxoEndpointClient

ADDRESS = "tcp://localhost:5565"


def double(params, ctx):
    return params["x"] * 2


USER_ID = "local"
VIRTUAL_ENVIRONMENT_ID = "default"


def main():
    with AxoEndpointClient(ADDRESS) as client:
        register_result = client.register_function(
            USER_ID, VIRTUAL_ENVIRONMENT_ID, "double", fn=double,
            runtime_spec={"type": "container", "python_version": "3.10"},
        )
        print("registered:", register_result.metadata)
        version = register_result.metadata["version"]
        for i in range(10):
            result = client.run(USER_ID, VIRTUAL_ENVIRONMENT_ID, "double", version, {"x": i})
            print("result:", result.metadata)


if __name__ == "__main__":
    main()
