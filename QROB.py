"""
QROB (Quantum Realization Overhead Benchmark): reverse-construction benchmark
generator for quantum circuit routing.

QROB builds routing benchmarks "in reverse": it first generates a circuit that
is directly executable on a target coupling map, then injects influence-guided
scrambling SWAPs while recording their inverses. The recorded inverse sequence
is a built-in reference routing solution for the resulting compilation
instance, so every benchmark ships with a feasible, compiler-independent
reference SWAP count.

This module is a trimmed version of the generator used for the MICRO 2026
paper "QROB: Quantifying Realization Overhead in Quantum Compilation via
Reverse Construction" (arXiv:2609.07776; artifact DOI: 10.5281/zenodo.21539550).
The generation logic is unchanged; legacy experiment code was removed and
comments were translated to English.

Typical entry point: `ReverseSABRE_QROB_with_IR.generate_benchmark()`, or the
dataset driver `benchmarkGen.py`.
"""

import networkx as nx
import random
import numpy as np


def generate_grid_topology(n, m):
    """
    Build the edge list of an n x m grid topology.

    Args:
        n: number of rows
        m: number of columns

    Returns:
        list: tuples (q1, q2) for all nearest-neighbor connections
    """
    connections = []

    for row in range(n):
        for col in range(m - 1):
            node1 = row * m + col
            node2 = row * m + col + 1
            connections.append((node1, node2))

    for row in range(n - 1):
        for col in range(m):
            node1 = row * m + col
            node2 = (row + 1) * m + col
            connections.append((node1, node2))

    return connections


def convert_data_format(data):
    """
    Convert [((a, b), c, d), ...] into [((a, b), (c, d)), ...].

    Used to turn the internal disruption-SWAP records into the
    (swap, position) format stored in QROBCircuit.swap_history.
    """
    result = []

    for item in data:
        (a, b), c, d = item
        converted_item = ((a, b), (c, d))
        result.append(converted_item)

    return result


class QROBCircuit:
    """
    A layered quantum circuit together with its SWAP insertion history
    and the current logical-to-physical qubit mapping.
    """

    def __init__(self):
        self.layers = []  # List of circuit layers
        self.swap_history = []  # List of applied SWAPs with their positions
        self.logical_to_physical = {}  # Current mapping of logical to physical qubits
        self.physical_to_logical = {}  # Current mapping of physical to logical qubits
        self.applied_swaps = []  # List of applied SWAPs in the order they were applied
        self.all_swaps = []  # All SWAPs that have been applied, including those not in the current mapping

    def add_layer(self, layer):
        """Add a new layer to the circuit"""
        self.layers.append(layer)

    def add_swap(self, swap_gate, position):
        """Record a SWAP operation in the history and update the mapping"""
        self.swap_history.append((swap_gate, position))
        self.applied_swaps.append((swap_gate, position))

        phys_q1, phys_q2 = swap_gate
        log_q1 = self.physical_to_logical[phys_q1]
        log_q2 = self.physical_to_logical[phys_q2]

        self.logical_to_physical[log_q1] = phys_q2
        self.logical_to_physical[log_q2] = phys_q1
        self.physical_to_logical[phys_q1] = log_q2
        self.physical_to_logical[phys_q2] = log_q1

    def initialize_mapping(self, num_qubits):
        """Initialize with identity mapping"""
        self.logical_to_physical = {i: i for i in range(num_qubits)}
        self.physical_to_logical = {i: i for i in range(num_qubits)}

    def get_executable_circuit(self):
        """Return the circuit in a form that's directly executable on the hardware"""
        executable_circuit = []

        for layer in self.layers:
            exec_layer = []
            for gate in layer:
                if len(gate) == 1:  # Single-qubit gate
                    phys_qubit = self.logical_to_physical[gate[0]]
                    exec_layer.append((phys_qubit,))
                else:  # Two-qubit gate
                    phys_qubit1 = self.logical_to_physical[gate[0]]
                    phys_qubit2 = self.logical_to_physical[gate[1]]
                    exec_layer.append((phys_qubit1, phys_qubit2))
            executable_circuit.append(exec_layer)
        return executable_circuit

    def confuse_circuit(self):
        """Create a confused version by permuting qubit labels"""
        num_qubits = len(self.logical_to_physical)

        # Generate a random permutation
        shuffled_indices = list(range(num_qubits))
        random.shuffle(shuffled_indices)

        # Create mapping dictionaries
        orig_to_confused = {i: shuffled_indices[i] for i in range(num_qubits)}
        confused_to_orig = {shuffled_indices[i]: i for i in range(num_qubits)}

        # Apply the permutation to the circuit
        confused_circuit = QROBCircuit()
        confused_circuit.initialize_mapping(num_qubits)

        for layer in self.layers:
            confused_layer = []
            for gate in layer:
                if len(gate) == 1:  # Single-qubit gate
                    confused_layer.append((orig_to_confused[gate[0]],))
                else:  # Two-qubit gate
                    confused_layer.append((orig_to_confused[gate[0]], orig_to_confused[gate[1]]))
            confused_circuit.add_layer(confused_layer)

        # Translate the SWAP history
        for swap_gate, position in self.swap_history:
            phys_q1, phys_q2 = swap_gate
            confused_swap = (orig_to_confused[phys_q1], orig_to_confused[phys_q2])
            confused_circuit.swap_history.append((confused_swap, position))

        return confused_circuit, orig_to_confused, confused_to_orig

    def to_qiskit_circuit_accurate(self):
        """
        Convert the QROBCircuit to a Qiskit QuantumCircuit.

        Single-qubit gates are emitted as H and two-qubit gates as CX
        (placeholder gate types; routing cost only depends on the
        two-qubit interaction structure).

        Returns:
            qiskit.QuantumCircuit: The converted circuit
        """
        from qiskit import QuantumCircuit

        num_qubits = len(self.logical_to_physical)
        qc = QuantumCircuit(num_qubits)

        for layer_idx, layer in enumerate(self.layers):
            # Find SWAPs that need to be applied before this layer
            swaps_for_layer = [(swap, pos) for swap, pos in self.swap_history
                               if pos[0] == layer_idx and not any(
                    p[0] == pos[0] and p[1] < pos[1] for _, p in self.swap_history)]
            if len(swaps_for_layer) > 0:
                for swap in swaps_for_layer:
                    qc.swap(swap[0][0], swap[0][1])

            for gate_idx, gate in enumerate(layer):
                if len(gate) == 1:  # Single-qubit gate
                    qc.h(gate[0])  # Using Hadamard as placeholder
                else:  # Two-qubit gate
                    qc.cx(gate[0], gate[1])  # Using CNOT as placeholder

        return qc

    @classmethod
    def from_qiskit_circuit(cls, qiskit_circuit):
        """
        Convert a Qiskit QuantumCircuit to a QROBCircuit, following the
        DAG layer structure of the Qiskit circuit. Only CX gates are kept.

        Args:
            qiskit_circuit (qiskit.QuantumCircuit): circuit to convert

        Returns:
            QROBCircuit: the converted circuit
        """
        from qiskit.converters import circuit_to_dag

        qrob_circuit = cls()

        # Identity initial mapping
        num_qubits = qiskit_circuit.num_qubits
        qrob_circuit.initialize_mapping(num_qubits)

        # Convert to a DAG to recover the layer structure
        dag = circuit_to_dag(qiskit_circuit)

        layers = []
        for layer in dag.layers():
            current_layer_gates = []
            for node in layer['graph'].op_nodes():
                if node.op.name == 'cx':
                    qubits = [qiskit_circuit.find_bit(qubit).index for qubit in node.qargs]
                    control, target = qubits
                    current_layer_gates.append((control, target))

            if current_layer_gates:  # Only keep layers that contain CX gates
                layers.append(current_layer_gates)

        for layer in layers:
            qrob_circuit.add_layer(layer)

        return qrob_circuit


class QROBLayer:
    """Class representing a single layer of quantum gates"""

    def __init__(self):
        self.single_qubit_gates = []
        self.two_qubit_gates = []
        self.used_qubits = set()

    def add_single_gate(self, qubit):
        """Add a single-qubit gate if the qubit is available"""
        if qubit in self.used_qubits:
            return False
        self.single_qubit_gates.append(qubit)
        self.used_qubits.add(qubit)
        return True

    def add_two_qubit_gate(self, qubit1, qubit2):
        """Add a two-qubit gate if both qubits are available"""
        if qubit1 in self.used_qubits or qubit2 in self.used_qubits:
            return False
        self.two_qubit_gates.append((qubit1, qubit2))
        self.used_qubits.add(qubit1)
        self.used_qubits.add(qubit2)
        return True

    def get_gates(self):
        """Return all gates in the layer"""
        gates = [(q,) for q in self.single_qubit_gates]
        gates.extend(self.two_qubit_gates)
        return gates


class QROB:
    """
    QROB base class: holds the device topology and generates circuits
    that are directly executable on it.
    """

    def __init__(self,
                 connection_list,
                 depth_range=(10, 20),
                 gate_density=(0.1, 0.2),
                 swap_complexity=(0.05, 0.1),
                 routing_difficulty=1.0,
                 name=None):
        self.routing_difficulty = routing_difficulty

        # Initialize parameters
        self.connection_list = connection_list
        self.device_layout = nx.Graph()
        self.device_layout.add_edges_from(self.connection_list)

        self.min_depth, self.max_depth = depth_range
        self.gate_density = gate_density
        self.swap_complexity = swap_complexity

        # Set name for output files
        if name:
            self.name = name
        else:
            self.name = f"qrob_depth{self.min_depth}-{self.max_depth}_gate{gate_density[0]}-{gate_density[1]}_swap{swap_complexity[0]}-{swap_complexity[1]}"

        # Extract device information
        self.nodes = list(self.device_layout.nodes())
        self.edges = list(self.device_layout.edges())
        self.count_node = len(self.nodes)
        self.count_edge = len(self.edges)

        # Validate parameters
        self._validate_parameters()

        # Generate the circuit
        self.circuit = None
        self.confused_circuit = None
        self.qrob_result = None

    def _validate_parameters(self):
        """Check if the parameters are valid"""
        if self.min_depth <= 0 or self.max_depth <= 0:
            raise ValueError("Depth must be positive integer.")
        if self.min_depth > self.max_depth:
            raise ValueError("Minimum depth cannot be greater than maximum depth.")

        if self.gate_density[0] < 0 or self.gate_density[1] < 0:
            raise ValueError("Gate density must be non-negative.")

        if self.swap_complexity[0] < 0 or self.swap_complexity[1] < 0:
            raise ValueError("SWAP complexity must be non-negative.")
        if self.swap_complexity[0] > self.swap_complexity[1]:
            raise ValueError("Minimum SWAP ratio cannot be greater than maximum SWAP ratio.")

    def _is_executable(self, circuit, edge):
        """Check whether a two-qubit gate is executable under the current mapping"""
        q1, q2 = edge
        phys_q1 = circuit.logical_to_physical[q1]
        phys_q2 = circuit.logical_to_physical[q2]

        edge1 = (phys_q1, phys_q2)
        edge2 = (phys_q2, phys_q1)

        return edge1 in self.edges or edge2 in self.edges

    def generate_executable_circuit(self):
        """
        Generate a circuit that is directly executable on the target topology.
        Only two-qubit gates are used, and repeating the same CX gate in
        adjacent layers is avoided.
        """
        # Pick the circuit depth
        target_depth = random.randint(self.min_depth, self.max_depth)

        # Create the circuit object
        circuit = QROBCircuit()
        circuit.initialize_mapping(self.count_node)

        # Remember gates used in the last few layers to avoid short-term repeats
        recent_gates = []  # One set of gates per recent layer
        memory_length = 2  # Number of recent layers to remember

        for layer_idx in range(target_depth):
            layer = QROBLayer()

            # Number of gates to place in this layer, from the gate density
            _, two_gate_density = self.gate_density
            expected_two_gates = max(1, int(two_gate_density * self.count_node / 2))

            # Collect gates used in the recent layers
            recent_used_gates = set()
            for gate_set in recent_gates:
                recent_used_gates.update(gate_set)

            # Gates used in the current layer
            current_layer_gates = set()

            # Add two-qubit gates (only between physically connected qubits)
            available_edges = list(self.edges)
            random.shuffle(available_edges)

            # Prefer edges that were not used in the recent layers
            preferred_edges = [edge for edge in available_edges
                               if ((circuit.physical_to_logical[edge[0]],
                                    circuit.physical_to_logical[edge[1]]) not in recent_used_gates) and
                               ((circuit.physical_to_logical[edge[1]],
                                 circuit.physical_to_logical[edge[0]]) not in recent_used_gates)]

            # If there are not enough unused edges, fall back to all edges
            if len(preferred_edges) < expected_two_gates:
                remaining_edges = [edge for edge in available_edges if edge not in preferred_edges]
                preferred_edges.extend(remaining_edges)

            gates_added = 0

            for edge in preferred_edges:
                if gates_added >= expected_two_gates:
                    break

                phys_q1, phys_q2 = edge
                log_q1 = circuit.physical_to_logical[phys_q1]
                log_q2 = circuit.physical_to_logical[phys_q2]

                # Add the gate if both qubits are still free in this layer
                if log_q1 not in layer.used_qubits and log_q2 not in layer.used_qubits:
                    if layer.add_two_qubit_gate(log_q1, log_q2):
                        gate_pair = (log_q1, log_q2) if log_q1 < log_q2 else (log_q2, log_q1)
                        current_layer_gates.add(gate_pair)
                        gates_added += 1

            circuit.add_layer(layer.get_gates())

            # Update the record of recently used gates
            recent_gates.append(current_layer_gates)
            if len(recent_gates) > memory_length:
                recent_gates.pop(0)

        # If the converted depth falls short of the target, keep padding
        while True:
            qiskit_circuit = circuit.to_qiskit_circuit_accurate()
            actual_depth = qiskit_circuit.depth()

            if actual_depth >= target_depth:
                break

            # Add one more layer containing a single gate
            layer = QROBLayer()
            available_edges = list(self.edges)
            random.shuffle(available_edges)

            for edge in available_edges:
                phys_q1, phys_q2 = edge
                log_q1 = circuit.physical_to_logical[phys_q1]
                log_q2 = circuit.physical_to_logical[phys_q2]

                if layer.add_two_qubit_gate(log_q1, log_q2):
                    break  # One gate is enough

            circuit.add_layer(layer.get_gates())

        self.circuit = QROBCircuit.from_qiskit_circuit(circuit.to_qiskit_circuit_accurate())
        return self.circuit


class ReverseSABRE_QROB(QROB):
    """
    Reverse-construction benchmark base class.

    The benchmark is created by:
    1. generating a circuit directly executable on the given topology,
    2. deliberately adding non-redundant SWAPs so that some two-qubit
       gates become non-executable,
    3. recording those SWAPs as a known reference SWAP sequence,
    4. producing a scrambled (confused) version for testing routers.
    """

    def __init__(self,
                 connection_list,
                 depth_range=(10, 20),
                 gate_density=(0.1, 0.2),
                 swap_complexity=(0.05, 0.1),
                 routing_difficulty=1.0,
                 name=None):

        super().__init__(connection_list, depth_range, gate_density,
                         swap_complexity, routing_difficulty, name)

        if name:
            self.name = name
        else:
            self.name = f"reverse_sabre_qrob_d{self.min_depth}-{self.max_depth}_g{gate_density[0]}-{gate_density[1]}_s{swap_complexity[0]}-{swap_complexity[1]}"

        # Extra bookkeeping for benchmark generation
        self.disruption_history = []  # History of disruption operations
        self.repair_swaps = []  # Recorded repair SWAP sequence
        self.original_circuit = None

    def _clone_circuit(self, circuit):
        """Create a copy of a circuit"""
        clone = QROBCircuit()
        clone.layers = circuit.layers.copy()
        clone.swap_history = circuit.swap_history.copy()
        clone.logical_to_physical = circuit.logical_to_physical.copy()
        clone.physical_to_logical = circuit.physical_to_logical.copy()
        if hasattr(circuit, 'applied_swaps'):
            clone.applied_swaps = circuit.applied_swaps.copy()
        return clone


def check_circuit_executable_fast(qc, coupling_list):
    """
    Check whether a Qiskit circuit is directly executable on a coupling map
    (i.e. needs no routing), using Qiskit's CheckMap pass.

    Args:
        qc: QuantumCircuit object
        coupling_list: list of edges, e.g. [(0, 1), (1, 2), ...]

    Returns:
        bool: True if the circuit is executable as-is
    """
    try:
        from qiskit.transpiler.passes import CheckMap
        from qiskit.transpiler import CouplingMap, PassManager

        coupling_map = CouplingMap(couplinglist=coupling_list)

        pm = PassManager()
        pm.append(CheckMap(coupling_map))
        pm.run(qc)

        # CheckMap is an analysis pass: its verdict is stored in the property set
        return bool(pm.property_set['is_swap_mapped'])

    except Exception as e:
        print(f"Error during executability check: {e}")
        return False


def remove_swaps_from_qiskit_circuit(circuit):
    """
    Remove all SWAP gates from a Qiskit circuit.

    Args:
        circuit: Qiskit QuantumCircuit object

    Returns:
        QuantumCircuit: a new circuit without SWAP gates
    """
    from qiskit import QuantumCircuit

    num_qubits = circuit.num_qubits
    num_clbits = circuit.num_clbits
    new_circuit = QuantumCircuit(num_qubits, num_clbits)

    for instruction in circuit.data:
        if instruction.operation.name != 'swap':
            new_circuit.append(instruction.operation, instruction.qubits, instruction.clbits)

    return new_circuit


class IRConfig:
    """
    Influence-weighting configuration for scrambling-SWAP placement.

    Each candidate SWAP is scored by its weighted impact on future circuit
    layers (the influence score of the paper, Sec. III-C); the weighting
    profile controls the emulated lookahead behaviour. Code-level strategies
    and their paper names:
    - global_view (GV): all future layers weighted equally     -> paper "Global"
    - tactical_focus (TF): hard cutoff after a fixed radius    -> paper "Cut-Off"
    - default: smoothly decaying weight on future layers       -> paper "Decay"
    - strategic_lookahead (SL): linear window (extra variant)
    - baseline (BL): next layer only (extra variant)
    """

    def __init__(self, name, r_eff_func, alpha_func):
        """
        Initialize an IR configuration.

        Args:
            name (str): Name of the IR configuration
            r_eff_func (callable): Function to calculate effective radius given current layer l and circuit depth d
            alpha_func (callable): Function to calculate weight for a layer at distance i within the radius
        """
        self.name = name
        self.r_eff_func = r_eff_func
        self.alpha_func = alpha_func

    def get_r_eff(self, l, d):
        """
        Get the effective influence radius for the current layer.

        Args:
            l (int): Current decision layer index (0-based)
            d (int): Total circuit depth

        Returns:
            int: Effective influence radius
        """
        return self.r_eff_func(l, d)

    def get_alpha(self, i, r_eff):
        """
        Get the weight for a layer at distance i within the radius.

        Args:
            i (int): Distance of the future layer from current decision layer (0-based)
            r_eff (int): Effective influence radius

        Returns:
            float: Weight for the layer
        """
        return self.alpha_func(i, r_eff)

    @classmethod
    def global_view(cls):
        """
        IR-GlobalView (GV): Aims to maximize global and extremely long-range effects.

        Returns:
            IRConfig: GlobalView IR configuration
        """

        def r_eff_func(l, d):
            return d - l  # Cover all future layers from current layer to the end

        def alpha_func(i, r_eff):
            return 1.0 if i < r_eff else 0.0  # Equal weight for all layers within radius

        return cls("IR_GV_ConstantFull", r_eff_func, alpha_func)

    @classmethod
    def strategic_lookahead(cls, strategic_ratio=0.3):
        """
        IR-StrategicLookahead (SL): Simulates strategic mid to long-range planning.

        Args:
            strategic_ratio (float): Ratio of circuit depth to use as strategic radius

        Returns:
            IRConfig: StrategicLookahead IR configuration
        """

        def r_eff_func(l, d):
            # Strategic radius based on typical depth
            r_strategic = max(2, int(d * strategic_ratio))
            return min(r_strategic, d - l)  # Cannot exceed remaining layers

        def alpha_func(i, r_eff):
            # Linear decrease from 1.0 at i=0 to 1/r_eff at i=r_eff-1
            return (r_eff - i) / r_eff if i < r_eff else 0.0

        return cls("IR_SL_LinearWindow", r_eff_func, alpha_func)

    @classmethod
    def tactical_focus(cls, r_tactical=3):
        """
        IR-TacticalFocus (TF): Simulates tactical short-term/local effects.

        Args:
            r_tactical (int): Fixed small value for tactical radius

        Returns:
            IRConfig: TacticalFocus IR configuration
        """

        def r_eff_func(l, d):
            return min(r_tactical, d - l)  # Cannot exceed remaining layers

        def alpha_func(i, r_eff):
            return 1.0 if i < r_eff else 0.0  # Equal weight for all layers within small radius

        return cls("IR_TF_HardCutoff", r_eff_func, alpha_func)

    @classmethod
    def baseline(cls):
        """
        IR-Baseline (BL): Acts as a control group or basic comparison benchmark.

        Returns:
            IRConfig: Baseline IR configuration
        """

        def r_eff_func(l, d):
            return min(1, d - l)  # Only look at the next layer

        def alpha_func(i, r_eff):
            return 1.0 if i == 0 else 0.0  # Only consider immediate next layer

        return cls("IR_BL_GreedyNextLayer", r_eff_func, alpha_func)

    @classmethod
    def default(cls, decay_constant=0.1):
        """
        IR-Default: full lookahead with smoothly decaying weights
        alpha(i) = 1 / (1 + i * decay_constant).
        """
        def r_eff_func(l, d):
            return d - l  # Always look to the end of the circuit

        def alpha_func(i, r_eff):  # r_eff is unused here since the radius is always global
            return 1.0 / (1 + i * decay_constant)

        return cls(f"IR_default_{decay_constant}", r_eff_func, alpha_func)


class ReverseSABRE_QROB_with_IR(ReverseSABRE_QROB):
    """
    Enhanced version of ReverseSABRE_QROB that incorporates IR configurations
    for more controllable and varied benchmark generation.
    """

    def __init__(self,
                 connection_list,
                 depth_range=(10, 20),
                 gate_density=(0.1, 0.2),
                 swap_complexity=(0.05, 0.1),
                 routing_difficulty=1.0,
                 ir_config=None,
                 name=None):

        super().__init__(connection_list, depth_range, gate_density,
                         swap_complexity, routing_difficulty, name)

        # Set default IR configuration if none provided
        self.ir_config = ir_config if ir_config else IRConfig.baseline()

        # Update name to include IR configuration
        if name is None:
            ir_suffix = self.ir_config.name.replace("IR_", "").lower()
            self.name = f"reverse_sabre_qrob_d{self.min_depth}-{self.max_depth}_g{gate_density[0]}-{gate_density[1]}_s{swap_complexity[0]}-{swap_complexity[1]}_{ir_suffix}"

    def evaluate_swap_impact(self, circuit, swap, layer_idx, initial_mapping=None):
        """
        Evaluate impact of a SWAP on future layers using IR configuration.

        Args:
            circuit (QROBCircuit): Circuit being modified
            swap (tuple): SWAP operation as (phys_qubit1, phys_qubit2)
            layer_idx (int): Index of the current layer
            initial_mapping (dict, optional): logical-to-physical mapping to
                reset both circuits to before the evaluation

        Returns:
            tuple: (affected_gates_count, total_weight) - impact metrics
        """
        # Create temporary circuit to simulate SWAP effect
        temp_circuit = self._clone_circuit(circuit)
        if initial_mapping is not None:
            temp_circuit.logical_to_physical = initial_mapping.copy()
            temp_circuit.physical_to_logical = {v: k for k, v in initial_mapping.items()}
            circuit.logical_to_physical = initial_mapping.copy()
            circuit.physical_to_logical = {v: k for k, v in initial_mapping.items()}
        else:
            temp_circuit.initialize_mapping(self.count_node)
            circuit.initialize_mapping(self.count_node)

        temp_circuit.add_swap(swap, (layer_idx, -1))
        # Calculate effective radius based on IR configuration
        circuit_depth = len(temp_circuit.layers)
        r_eff = self.ir_config.get_r_eff(layer_idx, circuit_depth)

        # Calculate the range of layers to consider
        max_layer = min(circuit_depth - 1, layer_idx + r_eff - 1)

        # Count affected gates and calculate weighted impact
        affected_gates = 0
        total_weight = 0
        swap_record = {
            'swap': swap,
            'gates': [],
            'affected_gates': 0
        }
        for check_layer_idx in range(layer_idx, max_layer + 1):
            # Calculate the distance from current layer
            i = check_layer_idx - layer_idx

            # Get weight for this layer based on IR configuration
            alpha = self.ir_config.get_alpha(i, r_eff)

            # Skip if weight is zero
            if alpha <= 0:
                continue

            # Check gates in this layer
            for gate_idx, gate in enumerate(temp_circuit.layers[check_layer_idx]):
                if len(gate) == 2:  # Only consider two-qubit gates
                    # Check if gate was executable before SWAP
                    original_executable = self._is_executable(circuit, gate)
                    # Check if gate is executable after SWAP
                    new_executable = self._is_executable(temp_circuit, gate)
                    # If gate changed from executable to non-executable
                    swap_record['gates'].append([gate, original_executable, new_executable])
                    if original_executable and not new_executable:
                        affected_gates += 1
                        total_weight += alpha
                    elif new_executable and not original_executable:
                        # May affect downstream gates in the other direction
                        affected_gates -= 1
                        total_weight -= alpha
        swap_record['affected_gates'] = affected_gates

        return affected_gates, total_weight

    def generate_benchmark(self, mode="performance", target_depth=None, gate_density=None):
        """
        Generate benchmark circuit using the selected IR configuration.

        Args:
            mode: "performance" or "config"
            target_depth: target depth (required in config mode)
            gate_density: gate density (required in config mode)
        """
        # Generate executable circuit
        if mode == "config":
            # Skeleton-fill generation with gate-density control
            if target_depth is None or gate_density is None:
                raise ValueError("config mode requires target_depth and gate_density")

            skeleton_generator = SkeletonCircuitGenerator(
                connection_list=self.connection_list,
                target_depth=target_depth,
                gate_density=gate_density
            )
            orign_c = skeleton_generator.generate_scaffold_fill_circuit_with_density()
            self.circuit = orign_c
            if orign_c is None:
                raise ValueError("Skeleton-fill circuit generation failed")

        else:
            # Original generation method
            orign_c = self.generate_executable_circuit()

        qiskit_circuit = orign_c.to_qiskit_circuit_accurate()
        actual_depth = qiskit_circuit.depth()
        actual_cx_gates = qiskit_circuit.count_ops().get('cx', 0)

        self.original_circuit = self.circuit
        # Record original mapping
        self.original_mapping = self.circuit.logical_to_physical.copy()

        # Storage for SWAP operations
        self.all_disruption_swaps = []
        self.all_repair_swaps = []

        # Traverse layers in reverse order
        layers = list(range(len(self.circuit.layers)))
        layers.reverse()

        # Calculate qubit usage by layer
        qubit_usage_by_layer = {}
        for layer_idx in layers:
            qubit_usage_by_layer[layer_idx] = {q: 0 for q in range(self.count_node)}
            for future_idx in range(layer_idx, len(self.circuit.layers)):
                for gate in self.circuit.layers[future_idx]:
                    if len(gate) == 2:
                        q1, q2 = gate
                        qubit_usage_by_layer[layer_idx][q1] += 1
                        qubit_usage_by_layer[layer_idx][q2] += 1

        # Determine total SWAPs to add based on swap_complexity
        min_swap_ratio, max_swap_ratio = self.swap_complexity
        num_two_qubit_gates = sum(sum(1 for gate in layer if len(gate) > 1) for layer in self.circuit.layers)
        total_swaps_to_add = max(1, int(random.uniform(min_swap_ratio, max_swap_ratio) * num_two_qubit_gates))

        # Track added SWAPs
        added_swaps = 0

        # Working circuit to track current state
        working_circuit = QROBCircuit()
        working_circuit.layers = self.circuit.layers.copy()
        working_circuit.logical_to_physical = self.original_mapping.copy()
        working_circuit.physical_to_logical = {v: k for k, v in self.original_mapping.items()}

        # Process layers from back to front
        for layer_idx in layers:
            # Exit if we've reached target SWAP count
            if added_swaps >= total_swaps_to_add:
                break
            # Get qubit usage for initial filtering
            qubit_usage = qubit_usage_by_layer[layer_idx]

            # Sort qubits by usage to narrow search
            sorted_qubits = sorted(qubit_usage.keys(), key=lambda q: qubit_usage[q], reverse=True)
            top_qubits = sorted_qubits[:min(6, len(sorted_qubits))]

            # Consider all possible SWAP candidates
            candidate_swaps = []

            for edge in self.edges:
                # Evaluate this SWAP's impact using IR configuration
                affected_gates, impact_weight = self.evaluate_swap_impact(working_circuit, edge, layer_idx)

                # If this SWAP affects at least one gate, add as candidate
                if affected_gates > 0:
                    # Score combines affected gates count and weight
                    score = affected_gates * 10 + impact_weight * 5
                    candidate_swaps.append((edge, score, affected_gates))
            # If no gate-affecting SWAPs found, try next layer
            if not candidate_swaps and layer_idx > 0:
                continue

            # Select highest-impact SWAP
            if candidate_swaps:

                # Sort by score and select highest
                candidate_swaps.sort(key=lambda x: x[1], reverse=True)
                selected_swap, score, affected = candidate_swaps[0]
                # Apply SWAP to working circuit
                working_circuit.add_swap(selected_swap, (layer_idx, -1))

                self.all_disruption_swaps.append((selected_swap, layer_idx, -1))

                # Record repair SWAP (reverse order of disruption SWAP)
                self.all_repair_swaps.insert(0, (selected_swap, layer_idx, -1))

                added_swaps += 1
                p1, p2 = selected_swap

                # Update affected gates
                # 1. Update previously added SWAP gates
                for i, (prev_swap, prev_layer, prev_gate) in enumerate(self.all_disruption_swaps[:-1]):
                    prev_p1, prev_p2 = prev_swap

                    # Check if previous SWAP is affected by current SWAP
                    updated_p1, updated_p2 = prev_p1, prev_p2

                    if prev_p1 == p1:
                        updated_p1 = p2
                    elif prev_p1 == p2:
                        updated_p1 = p1

                    if prev_p2 == p1:
                        updated_p2 = p2
                    elif prev_p2 == p2:
                        updated_p2 = p1

                    # Update if SWAP changed
                    if (updated_p1, updated_p2) != (prev_p1, prev_p2):
                        updated_swap = (min(updated_p1, updated_p2), max(updated_p1, updated_p2))
                        self.all_disruption_swaps[i] = (updated_swap, prev_layer, prev_gate)

                # 2. Similarly update repair SWAP sequence
                for i, (repair_swap, repair_layer, repair_gate) in enumerate(self.all_repair_swaps[1:]):
                    repair_p1, repair_p2 = repair_swap

                    # Check if repair SWAP is affected by current SWAP
                    updated_p1, updated_p2 = repair_p1, repair_p2

                    if repair_p1 == p1:
                        updated_p1 = p2
                    elif repair_p1 == p2:
                        updated_p1 = p1

                    if repair_p2 == p1:
                        updated_p2 = p2
                    elif repair_p2 == p2:
                        updated_p2 = p1

                    # Update if SWAP changed
                    if (updated_p1, updated_p2) != (repair_p1, repair_p2):
                        updated_swap = (min(updated_p1, updated_p2), max(updated_p1, updated_p2))
                        self.all_repair_swaps[i + 1] = (updated_swap, repair_layer, repair_gate)

                # 3. Update all gates
                for update_layer_idx in range(layer_idx, len(working_circuit.layers)):
                    updated_gates = []
                    for gate in working_circuit.layers[update_layer_idx]:
                        if len(gate) == 1:  # Single-qubit gate
                            q = gate[0]
                            # Build the swap relabeling map
                            swap_map = {p1: p2, p2: p1}
                            # Apply it
                            q = swap_map.get(q, q)
                            updated_gates.append((q,))
                        elif len(gate) == 2:  # Two-qubit gate
                            q1, q2 = gate

                            # Build the swap relabeling map
                            swap_map = {p1: p2, p2: p1}

                            # Apply it
                            q1 = swap_map.get(q1, q1)
                            q2 = swap_map.get(q2, q2)

                            updated_gates.append((q1, q2))

                    # Replace this layer with the updated gates
                    working_circuit.layers[update_layer_idx] = updated_gates

                # Refresh the SWAP history after all layers were updated
                working_circuit.swap_history = convert_data_format(self.all_disruption_swaps)

        # Update circuit to working circuit
        c = working_circuit.from_qiskit_circuit(working_circuit.to_qiskit_circuit_accurate())

        self.circuit = working_circuit

        # Create confused version
        self.confused_circuit = c
        # Save test set results
        self.qrob_result = {
            'original_circuit': self.original_circuit.get_executable_circuit(),
            'confused_circuit': self.confused_circuit.get_executable_circuit(),
            'all_disruption_swaps': self.all_disruption_swaps,
            'all_repair_swaps': self.all_repair_swaps,
            'original_mapping': self.original_mapping,
            'ir_config': self.ir_config.name
        }

        return self.qrob_result


class SkeletonCircuitGenerator:
    """
    Skeleton-fill circuit generator.

    Generates executable circuits with precise control over depth
    (via an incompressible skeleton path) and gate count (via a
    per-layer gate-density fill).
    """

    def __init__(self, connection_list, target_depth, gate_density):
        """
        Initialize the skeleton generator.

        Args:
            connection_list: device topology edge list
            target_depth: target circuit depth
            gate_density: gate density (float in [0, 1])
        """
        self.connection_list = connection_list
        self.target_depth = target_depth
        self.gate_density = gate_density

        # Build the topology graph
        self.device_layout = nx.Graph()
        self.device_layout.add_edges_from(self.connection_list)
        self.nodes = list(self.device_layout.nodes())
        self.edges = list(self.device_layout.edges())
        self.count_node = len(self.nodes)

        # Target gate count per layer
        self.gates_per_layer = self._calculate_gates_per_layer()

    def _calculate_gates_per_layer(self):
        """
        Compute the number of gates per layer from the gate density.

        Returns:
            int: target gates per layer
        """
        # Theoretical maximum: one CX occupies 2 qubits
        max_gates_per_layer = self.count_node // 2

        # Actual target: qubits * density / 2, rounded up
        target_gates = int(np.ceil(self.count_node * self.gate_density / 2))

        # Cannot exceed the theoretical maximum
        gates_per_layer = min(target_gates, max_gates_per_layer)

        return gates_per_layer

    def fill_additional_gates_with_density(self, skeleton_circuit):
        """
        Fill additional gates into the skeleton circuit according to
        the per-layer gate-density target.

        Args:
            skeleton_circuit: the skeleton circuit object

        Returns:
            QROBCircuit: the filled circuit
        """
        filled_layers = 0

        for layer_idx, layer in enumerate(skeleton_circuit.layers):
            # Count existing two-qubit gates in this layer
            current_two_qubit_gates = sum(1 for gate in layer if len(gate) == 2)

            # How many more gates this layer needs
            gates_to_add = self.gates_per_layer - current_two_qubit_gates

            if gates_to_add <= 0:
                continue

            # Qubits already used in this layer
            used_qubits = set()
            for gate in layer:
                if len(gate) == 1:
                    used_qubits.add(gate[0])
                else:
                    used_qubits.update(gate)

            # Edges whose both endpoints are still free
            available_edges = []
            for edge in self.edges:
                q1, q2 = edge
                if q1 not in used_qubits and q2 not in used_qubits:
                    available_edges.append(edge)

            # Add gates until the density target is met or no edges remain
            added_gates = 0
            for _ in range(gates_to_add):
                if not available_edges:
                    break

                # Pick a random available edge
                selected_edge = random.choice(available_edges)
                skeleton_circuit.layers[layer_idx].append(selected_edge)

                # Update used qubits and the available edge set
                used_qubits.update(selected_edge)
                available_edges = [edge for edge in available_edges
                                   if edge[0] not in used_qubits and edge[1] not in used_qubits]

                added_gates += 1

            if added_gates > 0:
                filled_layers += 1

        return skeleton_circuit

    def generate_scaffold_fill_circuit_with_density(self):
        """
        Generate a skeleton-fill circuit controlled by gate density.

        Returns:
            QROBCircuit: the generated executable circuit
        """
        # Step 1: generate the skeleton
        skeleton_gates = self.generate_skeleton_backbone()

        if not skeleton_gates:
            print("Warning: could not generate a valid skeleton path")
            return None

        # Create the skeleton circuit
        skeleton_circuit = QROBCircuit()
        skeleton_circuit.initialize_mapping(self.count_node)

        # One gate per layer, enforcing the serial dependency chain
        for gate in skeleton_gates:
            skeleton_circuit.layers.append([gate])

        # Step 2: fill additional gates according to the gate density
        filled_circuit = self.fill_additional_gates_with_density(skeleton_circuit)

        # Re-normalize the circuit structure through Qiskit
        processed_circuit = QROBCircuit.from_qiskit_circuit(filled_circuit.to_qiskit_circuit_accurate())

        # Validate the generated circuit
        self._verify_circuit_properties(processed_circuit)

        return processed_circuit

    def generate_skeleton_backbone(self):
        """
        Generate the incompressible skeleton path.

        Returns:
            List[Tuple[int, int]]: skeleton gate sequence
        """
        if self.target_depth <= 0:
            return []

        # Greedy longest path as the base skeleton
        skeleton_gates = self._find_greedy_longest_path()

        # Extend to the target depth (back-and-forth pattern)
        extended_skeleton = self._extend_to_target_depth(skeleton_gates)

        return extended_skeleton

    def _find_greedy_longest_path(self):
        """
        Greedily find a long simple path in the device graph.

        Returns:
            List[Tuple[int, int]]: base path gate sequence
        """
        if not self.nodes:
            return []

        # Start from a minimum-degree node (fewer dead ends)
        degrees = dict(self.device_layout.degree())
        min_degree = min(degrees.values())
        potential_starts = [node for node, degree in degrees.items() if degree == min_degree]
        start_node = random.choice(potential_starts)

        # Greedy path construction
        path = [start_node]
        visited = {start_node}
        current_node = start_node

        while True:
            neighbors = list(self.device_layout.neighbors(current_node))
            available_neighbors = [n for n in neighbors if n not in visited]

            if not available_neighbors:
                break

            # Prefer lower-degree neighbors
            neighbor_degrees = [(n, degrees[n]) for n in available_neighbors]
            neighbor_degrees.sort(key=lambda x: x[1])
            next_node = neighbor_degrees[0][0]

            path.append(next_node)
            visited.add(next_node)
            current_node = next_node

        # Convert the path into a gate sequence
        skeleton_gates = []
        for i in range(len(path) - 1):
            skeleton_gates.append((path[i], path[i + 1]))

        return skeleton_gates

    def _extend_to_target_depth(self, base_skeleton):
        """
        Extend the skeleton to the target depth with a back-and-forth pattern.

        Args:
            base_skeleton: base skeleton gate sequence

        Returns:
            List[Tuple[int, int]]: extended skeleton
        """
        if not base_skeleton:
            return []

        extended_skeleton = []
        direction_forward = True

        while len(extended_skeleton) < self.target_depth:
            if direction_forward:
                extended_skeleton.extend(base_skeleton)
            else:
                # Backward: reverse the path and flip each gate's direction
                reverse_gates = [(q2, q1) for q1, q2 in base_skeleton[::-1]]
                extended_skeleton.extend(reverse_gates)

            direction_forward = not direction_forward

            # Guard against infinite loops
            if len(extended_skeleton) > self.target_depth * 2:
                break

        return extended_skeleton[:self.target_depth]

    def _verify_circuit_properties(self, circuit):
        """
        Validate the generated circuit's depth and gate count.

        Args:
            circuit: circuit to validate
        """
        if circuit is None:
            return

        # Convert to Qiskit for depth validation
        qiskit_circuit = circuit.to_qiskit_circuit_accurate()
        actual_depth = qiskit_circuit.depth()

        # Count actual two-qubit gates
        actual_gates = sum(sum(1 for gate in layer if len(gate) == 2)
                           for layer in circuit.layers)


def count_swap_gates(qiskit_circuit):
    """Count the number of SWAP gates in a Qiskit circuit"""
    swap_count = 0
    for instruction in qiskit_circuit.data:
        if instruction.operation.name == 'swap':
            swap_count += 1
    return swap_count
