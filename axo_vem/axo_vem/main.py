import os

from dotenv import load_dotenv

from axo_vem.config import Config
from axo_vem.server import Server


def main() -> None:
    _env_file = os.environ.get("AXO_VEM_ENV_FILE", ".env")
    load_dotenv(dotenv_path=_env_file, override=False)
    config = Config()
    server = Server(config)
    try:
        server.start()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


if __name__ == "__main__":
    main()
