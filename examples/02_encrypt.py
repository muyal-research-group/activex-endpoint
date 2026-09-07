from axo_shared.client import AxoEndpointClient

def main():
    aec = AxoEndpointClient(
        address = "tcp://localhost:5555",
    )
    def f(*args, **kwargs):
        from rory.core.security.cryptosystem.liu import Liu
        liu = Liu()
        sk  = liu.generate_secret_key()
        x   = liu.encryptScalar(plaintext=1,secret_key=sk)
        print(f"Encrypted value: {x}")
        return x


    user_id = "local"
    virtual_environment_id = "default"

    result = aec.register_function(
        user_id = user_id,
        virtual_environment_id = virtual_environment_id,
        name    = "liu_encrypt",
        fn      = f
    )
    print(f"Register result: {result}")
    version = result.metadata["version"]

    invocation_result = aec.run(
        user_id = user_id,
        virtual_environment_id = virtual_environment_id,
        function_name = "liu_encrypt",
        params        = {},
        poll_interval = 0.1,
        timeout       = 60,
        version       = version

    )
    print(f"Invocation result: {invocation_result}")




if __name__ == "__main__":
    main()
