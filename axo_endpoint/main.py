import os
import signal

from dotenv import load_dotenv

from axo_endpoint.config import Config
from axo_endpoint.service.app import build_app


def _raise_keyboard_interrupt(signum, frame) -> None:
    raise KeyboardInterrupt()


def main() -> None:
    _env_file = os.environ.get("AXO_ENDPOINT_ENV_FILE", ".env.dev")
    load_dotenv(dotenv_path=_env_file, override=False)
    app = build_app(Config())
    # docker stop sends SIGTERM, whose default action is immediate
    # termination -- route it through the same graceful-shutdown path SIGINT
    # already takes, rather than adding a second shutdown call path.
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()


if __name__ == "__main__":
    main()
