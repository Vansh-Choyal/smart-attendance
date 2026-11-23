"""Download only the documented face-trained model; refuse unexpected content."""
import hashlib
from pathlib import Path
from urllib.request import urlopen

URL = "https://github.com/akanametov/yolo-face/releases/download/1.0.0/yolov8n-face.pt"
SHA256 = "d545bf1add5aa736a4febac4f4f9245a6d596cd0fe70d5d57989fe0cb9e626ca"
DESTINATION = Path(__file__).resolve().parents[1] / "models" / "yolov8n-face.pt"


def main():
    DESTINATION.parent.mkdir(exist_ok=True)
    if DESTINATION.exists() and hashlib.sha256(DESTINATION.read_bytes()).hexdigest() == SHA256:
        print(f"Face model verified: {DESTINATION}")
        return
    temporary = DESTINATION.with_suffix(".part")
    try:
        with urlopen(URL, timeout=60) as response, temporary.open("wb") as output:
            while chunk := response.read(1024*1024):
                output.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != SHA256:
            raise RuntimeError("Weight checksum mismatch. The upstream file may have changed; inspect its source before loading it.")
        temporary.replace(DESTINATION)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Face model downloaded and verified: {DESTINATION}")


if __name__ == "__main__":
    main()
