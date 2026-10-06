"""Read-only, verified local E5 tokenizer. No Hub or network loader."""

from functools import lru_cache
import hashlib
from importlib.metadata import version
import json
from pathlib import Path


MODEL_ID = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
PACKAGE_VERSION = "0.22.2"
ASSET_HASHES = {
    "special_tokens_map.json": "d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7",
    "tokenizer.json": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    "tokenizer_config.json": "a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b",
}


def passage(title: str, headings: tuple[str, ...], search_text: str) -> str:
    return f"passage: {title}\n{' > '.join(headings)}\n{search_text}"


class LocalE5:
    def __init__(self, path: Path, revision: str = REVISION) -> None:
        if revision != REVISION:
            raise ValueError("tokenizer_identity")
        try:
            # Lazy import: HTTP startup never imports the tokenizer library.
            from tokenizers import Tokenizer

            actual_version = version("tokenizers")
            if actual_version != PACKAGE_VERSION:
                raise ValueError
            files = {name: (path / name).read_bytes() for name in ASSET_HASHES}
            hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
            if hashes != ASSET_HASHES:
                raise ValueError
            self._tokenizer = Tokenizer.from_str(files["tokenizer.json"].decode("utf-8"))
            self._tokenizer.no_truncation()
            self._tokenizer.no_padding()
            probe = self._tokenizer.encode("test", add_special_tokens=True).ids
            if probe[0] != 0 or probe[-1] != 2:
                raise ValueError
            fingerprint = hashlib.sha256(json.dumps(
                hashes, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()
            self.identity = {"model_id": MODEL_ID, "revision": REVISION,
                             "assets_sha256": hashes, "assets_fingerprint": fingerprint,
                             "package": "tokenizers", "package_version": actual_version}
        except (ImportError, OSError, ValueError, UnicodeError):
            raise ValueError("tokenizer_assets") from None

    @lru_cache(maxsize=2048)
    def count(self, text: str, special: bool = False) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=special).ids)
