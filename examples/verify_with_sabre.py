"""
Route a QROB benchmark with Qiskit's SABRE and compare against the
built-in reference SWAP count.

QROB benchmarks are routing-only by construction: the scrambled circuit is
defined on physical qubits under an identity initial mapping, so a router
is run directly (no layout search). Run:
    python examples/verify_with_sabre.py
"""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from qiskit.transpiler import CouplingMap, PassManager
from qiskit.transpiler.passes import SabreSwap

from QROB import (
    IRConfig,
    ReverseSABRE_QROB_with_IR,
    check_circuit_executable_fast,
    count_swap_gates,
    generate_grid_topology,
)

random.seed(1)

topology = generate_grid_topology(5, 5)

print(f"{'instance':<10} {'reference':>9} {'sabre':>6} {'ratio':>6}")
for k in range(5):
    qrob = ReverseSABRE_QROB_with_IR(
        connection_list=topology,
        depth_range=(30, 30),
        gate_density=(0.3, 0.7),
        swap_complexity=(0.2, 0.4),
        ir_config=IRConfig.default(0.1),
        name=f"verify_{k}",
    )
    qrob.generate_benchmark(mode="config", target_depth=30, gate_density=0.5)

    original = qrob.original_circuit.to_qiskit_circuit_accurate()
    benchmark = qrob.confused_circuit.to_qiskit_circuit_accurate()
    reference = len(qrob.all_repair_swaps)

    # Sanity check: the pre-scrambling circuit must run without routing
    assert check_circuit_executable_fast(original, topology), \
        "executable circuit is not executable on the topology"

    # Route the benchmark with SABRE (decay heuristic, fixed seed)
    coupling_map = CouplingMap(couplinglist=topology)
    pm = PassManager([SabreSwap(coupling_map, heuristic="decay", seed=11)])
    routed = pm.run(benchmark)
    sabre = count_swap_gates(routed)

    # The routed circuit must now satisfy the coupling constraints
    routed_no_swaps_ok = check_circuit_executable_fast(routed, topology)
    assert routed_no_swaps_ok, "SABRE output violates the coupling map"

    ratio = sabre / reference if reference else float("inf")
    print(f"{k:<10} {reference:>9} {sabre:>6} {ratio:>6.2f}")

print("\nratio = SABRE SWAPs / QROB reference SWAPs (higher = more overhead)")
