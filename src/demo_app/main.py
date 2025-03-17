import argparse

from demo_app import app

DEFAULT_PORT = 5000


def parse_pargs() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", dest="port", type=int, default=DEFAULT_PORT)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_pargs()
    app.run(debug=True, port=args.port)
