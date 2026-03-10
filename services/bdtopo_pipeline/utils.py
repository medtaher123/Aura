from pathlib import Path


def read_urls_file(path: str) -> list[str]:
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Source URL file not found: {file_path}")

    urls: list[str] = []
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    if not urls:
        raise ValueError(f"Source URL file is empty: {file_path}")
    return urls


def parse_inline_urls(raw: str) -> list[str]:
    urls: list[str] = []
    for chunk in raw.replace(",", "\n").splitlines():
        line = chunk.strip()
        if line:
            urls.append(line)
    return urls
