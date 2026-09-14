"""Fly Golf simulation backend.

Simulated neural dynamics operating over the reconstructed MaleCNS connectome,
connected to a deterministic putting green. See the repository README for the
scientific caveats: the wiring is real anatomical data, the neuron dynamics are
modeled, and the sensory and motor mappings are engineered.
"""

__version__ = "0.1.0"

# Wire protocol version shared with packages/protocol/src/version.ts.
PROTOCOL_VERSION = 2
