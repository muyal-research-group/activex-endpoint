"""Run against a live node, e.g.:  ./axo_endpoint.sh --env-file .env.dev
Then:  python examples/05_client_registered_data.py
"""
import pickle

from axo_shared.client import AxoEndpointClient

ADDRESS = "tcp://localhost:5555"


def lookup_price(params, ctx):
    from axo_endpoint import dataio
    from axo_endpoint.core.dataio import IORef

    ref = IORef(kind="fs", location="prices/1", format="pickle")
    prices = dataio.read(ref)
    return prices.get(params["item"])


USER_ID = "local"
VIRTUAL_ENVIRONMENT_ID = "default"


def main():
    with AxoEndpointClient(ADDRESS) as client:
        register_result = client.register_function(USER_ID, VIRTUAL_ENVIRONMENT_ID, "lookup_price", fn=lookup_price)
        version = register_result.metadata["version"]

        # Register the data ONCE.
        catalog = {"apple": 1.50, "banana": 0.75, "cherry": 4.20}
        upload_result = client.upload_data("prices", 1, pickle.dumps(catalog), format="pickle")
        print("uploaded:", upload_result.metadata)

        # Run the SAME function multiple times against that SAME data.
        for item in ["apple", "banana", "cherry", "durian"]:
            result = client.run(USER_ID, VIRTUAL_ENVIRONMENT_ID, "lookup_price", version, {"item": item})
            print("Result for", item, "->", result)
            # print(item, "->", result.metadata["values"])


if __name__ == "__main__":
    main()
