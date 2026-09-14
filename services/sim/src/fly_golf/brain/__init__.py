"""Brain side of the loop: SensoryEncoder -> BrainController -> MotorDecoder -> MotorTarget.

Controllers are swappable behind `BrainController`. The MOCK controller is test
infrastructure; only `fly_golf.brain.malecns` runs the connectome.
"""
