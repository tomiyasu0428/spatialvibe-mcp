"""Isolated slicer plate writer. Only numeric geometry and escaped labels enter the archive."""
import json
import sys
from pathlib import Path
from ._runner import _plate_3mf


def main():
    scratch = Path(sys.argv[1])
    spec = json.loads((scratch / "inputs.json").read_text())
    result = {"labels": spec["labels"]}
    _plate_3mf(spec["parts"], result, scratch, spec["bed_mm"])
    (scratch / "plate.json").write_text(json.dumps(result["plate"]))


if __name__ == "__main__":
    main()
