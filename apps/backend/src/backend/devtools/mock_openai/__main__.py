import argparse

import uvicorn

from backend.devtools.mock_openai.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock OpenAI issuer + API (development only)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    print(f"Mock OpenAI — development only — http://{args.host}:{args.port}")
    print(f"  OPENAI_AUTH_ISSUER=http://{args.host}:{args.port}")
    print(f"  OPENAI_API_BASE_URL=http://{args.host}:{args.port}/v1")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
