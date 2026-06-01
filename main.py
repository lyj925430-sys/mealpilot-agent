from app.main import app


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, reload=True)


if __name__ == "__main__":
    main()
