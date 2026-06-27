from axo_endpoint.service.app import build_app
from axo_endpoint.service.config import Config


def main() -> None:
    app = build_app(Config())
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()


if __name__ == "__main__":
    main()
