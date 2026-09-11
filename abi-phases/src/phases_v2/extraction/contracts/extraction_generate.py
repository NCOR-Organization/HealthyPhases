"""Regenerate the checked-in descriptor with protoc 29.3 (make proto)."""

import hashlib
import subprocess
import tempfile
from pathlib import Path
from urllib.request import urlopen

SOURCE = "https://raw.githubusercontent.com/bufbuild/protovalidate/v1.0.0/proto/protovalidate/buf/validate/validate.proto"
SHA256 = "780f450e5e1b773cb6c52d32b93655ec915187d2c777aa9ddc0119b573c1e1d2"


def main():
    root = Path(__file__).resolve().parents[3]
    contracts = (
        "phases_v2/extraction/contracts/extraction_output.proto",
        "phases_v2/app/contracts/pipeline_management.proto",
    )
    with tempfile.TemporaryDirectory(prefix="phases-proto-") as temp:
        target = Path(temp) / "buf/validate/validate.proto"
        target.parent.mkdir(parents=True)
        with urlopen(SOURCE, timeout=30) as response:
            source = response.read()
        if hashlib.sha256(source).hexdigest() != SHA256:
            raise RuntimeError("Protovalidate dependency checksum mismatch")
        target.write_bytes(source)
        for contract in contracts:
            subprocess.run(
                [
                    "protoc",
                    "-I",
                    str(root),
                    "-I",
                    temp,
                    "--include_imports",
                    f"--descriptor_set_out={root / contract.replace('.proto', '.pb')}",
                    contract,
                ],
                check=True,
            )


if __name__ == "__main__":
    main()
