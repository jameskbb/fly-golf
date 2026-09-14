"""MaleCNS v1.0 adapter: the ONLY place connectome-specific logic lives.

- `graph.py`        load the compiled CSR graph + neuron table
- `engine.py`       Fly Golf's LIF engine `fly-golf-lif-v1` (Shiu et al. 2024 model, Brian2-exact)
- `legacy_engine.py` the previous, DOOMFLY-adapted engine: replay of old records and old readouts only
- `transmitters.py` transmitter -> synaptic sign proxy
- `populations.py`  documented sensory-injection and motor-readout populations
- `controller.py`   `MaleCNSController`, a `BrainController` implementation
"""
