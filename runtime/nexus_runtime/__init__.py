"""NEXUS local application core."""

import os

from ._version import VERSION  # noqa: F401

# Set before optional ML imports: prevents ONNX uploader/identifier initialization.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["DO_NOT_TRACK"] = "1"
