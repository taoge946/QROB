"""
Customize the two parts of QROB's construction:
  1. the influence weighting used to choose scrambling SWAPs (IRConfig), and
  2. the ideal (directly executable) circuit the construction starts from.

Run from the repository root or from examples/:
    python examples/custom_construction.py
"""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from qiskit import QuantumCircuit

from QROB import (
    IRConfig,
    QROBCircuit,
    ReverseSABRE_QROB_with_IR,
    check_circuit_executable_fast,
    generate_grid_topology,
)

random.seed(0)
topology = generate_grid_topology(4, 4)

# --- 1. Custom influence weighting -------------------------------------------
# r_eff_func(l, d): number of layers, starting at the current layer l, on which a
#                   candidate SWAP is evaluated (d = circuit depth)
# alpha_func(i, r_eff): weight of the layer i steps ahead (i = 0: the current layer)
window5_linear = IRConfig(
    "window5_linear",
    r_eff_func=lambda l, d: min(5, d - l),
    alpha_func=lambda i, r_eff: (r_eff - i) / r_eff,
)

qrob = ReverseSABRE_QROB_with_IR(
    connection_list=topology,
    depth_range=(20, 20),
    gate_density=(0.3, 0.7),      # unused in config mode
    swap_complexity=(0.2, 0.4),
    ir_config=window5_linear,
)
qrob.generate_benchmark(mode="config", target_depth=20, gate_density=0.5)
print(f"[custom weighting] reference SWAP count: {len(qrob.all_repair_swaps)}")


# --- 2. Custom ideal circuit -------------------------------------------------
# Any circuit whose CX gates all act on coupling-map edges can be the starting
# point; it is scrambled exactly like the built-in skeleton-fill circuits.
class QROBFromCircuit(ReverseSABRE_QROB_with_IR):
    """Scramble a user-supplied, directly executable circuit."""

    def __init__(self, ideal_circuit, **kwargs):
        super().__init__(**kwargs)
        self.ideal_circuit = ideal_circuit

    def generate_executable_circuit(self):
        # Only CX gates are kept; qubit i of the circuit sits on physical qubit i
        self.circuit = QROBCircuit.from_qiskit_circuit(self.ideal_circuit)
        return self.circuit


# Example ideal circuit: two alternating layers of disjoint CX gates on the
# 4x4 grid, repeated 6 times
layer_a = [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9), (10, 11), (12, 13), (14, 15)]
layer_b = [(0, 4), (1, 5), (2, 6), (3, 7), (8, 12), (9, 13), (10, 14), (11, 15)]
ideal = QuantumCircuit(16)
for _ in range(6):
    for q1, q2 in layer_a + layer_b:
        ideal.cx(q1, q2)
assert check_circuit_executable_fast(ideal, topology), "ideal circuit must be executable"

qrob2 = QROBFromCircuit(
    ideal,
    connection_list=topology,
    swap_complexity=(0.2, 0.4),
    ir_config=IRConfig.default(0.1),
)
qrob2.generate_benchmark()  # default mode builds the ideal circuit via generate_executable_circuit()

benchmark = qrob2.confused_circuit.to_qiskit_circuit_accurate()
print(f"[custom ideal circuit] depth={ideal.depth()}, cx={ideal.count_ops().get('cx', 0)}, "
      f"executable after scrambling: {check_circuit_executable_fast(benchmark, topology)}, "
      f"reference SWAP count: {len(qrob2.all_repair_swaps)}")
