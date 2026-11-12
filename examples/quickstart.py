"""
QROB quickstart: generate one routing benchmark with a built-in reference.

Run from the repository root or from examples/:
    python examples/quickstart.py
"""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from QROB import IRConfig, ReverseSABRE_QROB_with_IR, generate_grid_topology

random.seed(0)

# 1. Pick a device topology: a 4x4 grid (any edge list works, see chips/*.json)
topology = generate_grid_topology(4, 4)

# 2. Build the generator
qrob = ReverseSABRE_QROB_with_IR(
    connection_list=topology,
    depth_range=(20, 20),
    gate_density=(0.3, 0.7),          # unused in config mode
    swap_complexity=(0.2, 0.4),       # target SWAP fraction of 2q gates (at most one SWAP per layer)
    ir_config=IRConfig.default(0.1),  # influence weighting (paper: Decay)
    name="quickstart",
)

# 3. Generate: executable circuit -> disruption SWAPs -> scrambled benchmark
qrob.generate_benchmark(mode="config", target_depth=20, gate_density=0.5)

# 4. Inspect the results
original = qrob.original_circuit.to_qiskit_circuit_accurate()   # executable as-is
benchmark = qrob.confused_circuit.to_qiskit_circuit_accurate()  # input for routers
reference_swaps = len(qrob.all_repair_swaps)                    # built-in reference

print(f"Topology:            4x4 grid, {len(topology)} edges")
print(f"Executable circuit:  depth={original.depth()}, cx={original.count_ops().get('cx', 0)}")
print(f"Benchmark circuit:   depth={benchmark.depth()}, cx={benchmark.count_ops().get('cx', 0)}")
print(f"Reference SWAP count: {reference_swaps}")

# 5. Save the benchmark as QASM
from qiskit.qasm2 import dumps

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quickstart_benchmark.qasm")
with open(out, "w", encoding="utf-8") as f:
    f.write(dumps(benchmark))
print(f"Benchmark written to {out}")
