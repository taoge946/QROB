"""
QROB benchmark dataset generator (gate-density version, resume supported).

Generates, for one target chip, a suite of routing benchmarks with built-in
reference SWAP counts, across four size categories (S/M/L/XL) and four gate
densities (0.2/0.5/0.8/1.0). Output per instance:
  circuits/<id>.qasm              scrambled circuit handed to the router
  circuits/<id>_original.qasm     executable circuit before SWAP insertion
  metadata/<id>.json              full generation record
  reference_solutions/<id>_swaps.json   reference SWAP sequence and count

Usage:
  python benchmarkGen.py --chip quafu_baihua --output benchmark_dataset --seed 42
"""

import argparse
import os
import json
import time
import random
import numpy as np
import re
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd

from QROB import IRConfig, ReverseSABRE_QROB_with_IR


class BenchmarkDatasetGenerator:
    """Benchmark dataset generator with gate-density control and resume support"""

    def __init__(self, output_dir: str = "benchmark_dataset", target_chip: str = None, resume: bool = True):
        """
        Initialize the dataset generator.

        Args:
            output_dir: output directory
            target_chip: chip name; if given, only this chip is processed
            resume: whether to skip instances that already exist on disk
        """
        self.output_dir = output_dir
        self.target_chip = target_chip
        self.resume = resume

        # Create output directories
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, "circuits"), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "metadata"), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "reference_solutions"), exist_ok=True)

        # Record list
        self.benchmark_records = []

        # Scan existing circuits
        self.existing_circuits = self.scan_existing_circuits() if resume else {}

    def extract_chip_name(self, filename: str) -> str:
        """Extract the chip name from a filename, dropping any fidelity_map suffix"""
        name = filename.replace('.json', '')
        if name.endswith('_fidelity_map'):
            name = name[:-13]  # strip "_fidelity_map"
        return name

    def load_chip_data(self) -> Dict[str, Dict]:
        """Load chip data from the chips/ folder (fidelity information is ignored)"""
        chips_dir = "chips"
        chip_data = {}

        if not os.path.exists(chips_dir):
            raise FileNotFoundError(f"Chip data directory not found: {chips_dir}")

        # Collect the chip files to process
        chip_files = []
        for filename in os.listdir(chips_dir):
            if filename.endswith('.json'):
                chip_name = self.extract_chip_name(filename)

                # If a target chip is set, only process that chip
                if self.target_chip is None or chip_name == self.target_chip:
                    chip_files.append((filename, chip_name))

        if not chip_files:
            if self.target_chip:
                raise ValueError(f"Target chip not found: {self.target_chip}")
            else:
                raise ValueError("No chip files found in the chips directory")

        # Load chip data
        for filename, chip_name in chip_files:
            try:
                filepath = os.path.join(chips_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Extract the topology; fidelities are ignored
                topology = data.get('topology', [])
                if not topology:
                    print(f"Warning: chip {chip_name} has no topology information, skipping")
                    continue

                # Count qubits
                all_qubits = set()
                for edge in topology:
                    all_qubits.update(edge)
                num_qubits = len(all_qubits)

                chip_info = {
                    'topology': topology,
                    'num_qubits': num_qubits,
                    'num_edges': len(topology),
                    'vendor': data.get('vendor', 'Unknown'),
                    'architecture': data.get('architecture', 'Unknown'),
                    'gate_type': data.get('gate_type', 'CX')
                }

                chip_data[chip_name] = chip_info
                print(f"Loaded chip: {chip_name} ({num_qubits} qubits, {len(topology)} edges)")

            except Exception as e:
                print(f"Error loading chip {chip_name}: {e}")
                continue

        return chip_data

    def scan_existing_circuits(self) -> Dict:
        """Scan circuit files that already exist on disk"""
        if not self.target_chip:
            return {}

        circuits_dir = os.path.join(self.output_dir, "circuits")
        if not os.path.exists(circuits_dir):
            return {}

        print("Scanning existing circuits...")

        existing = {
            "by_size": {},
            "by_density": {},
            "total_count": 0,
            "files": []
        }

        # Filename format: chip_SIZE_dDENSITY_NUMBER.qasm
        pattern = re.compile(rf"^{self.target_chip}_([SMLX]+)_d([0-9\.]+)_(\d+)\.qasm$")

        for filename in os.listdir(circuits_dir):
            if filename.endswith("_original.qasm"):
                continue

            match = pattern.match(filename)
            if match:
                size = match.group(1)
                density = float(match.group(2))
                number = int(match.group(3))

                # Tally by size
                if size not in existing["by_size"]:
                    existing["by_size"][size] = {}
                if density not in existing["by_size"][size]:
                    existing["by_size"][size][density] = []
                existing["by_size"][size][density].append(number)

                # Tally by density
                if density not in existing["by_density"]:
                    existing["by_density"][density] = {}
                if size not in existing["by_density"][density]:
                    existing["by_density"][density][size] = []
                existing["by_density"][density][size].append(number)

                existing["files"].append(filename)
                existing["total_count"] += 1

        # Sort
        for size in existing["by_size"]:
            for density in existing["by_size"][size]:
                existing["by_size"][size][density].sort()

        if existing["total_count"] > 0:
            print(f"  Found {existing['total_count']} existing circuits")
            print(f"  By size:")
            for size in ["S", "M", "L", "XL"]:
                if size in existing["by_size"]:
                    total_for_size = sum(len(existing["by_size"][size][d]) for d in existing["by_size"][size])
                    print(f"    {size}: {total_for_size} circuits")
                    for density in sorted(existing["by_size"][size].keys()):
                        count = len(existing["by_size"][size][density])
                        numbers = existing["by_size"][size][density]
                        range_str = f"{min(numbers)}-{max(numbers)}" if count > 1 else str(numbers[0])
                        print(f"      density {density}: {count} circuits (numbers: {range_str})")
                else:
                    print(f"    {size}: 0 circuits")
        else:
            print("  No existing circuits found, will start from beginning")

        return existing

    def circuit_exists(self, benchmark_id: str) -> bool:
        """Check whether a benchmark instance already exists on disk"""
        circuit_file = os.path.join(self.output_dir, "circuits", f"{benchmark_id}.qasm")
        metadata_file = os.path.join(self.output_dir, "metadata", f"{benchmark_id}.json")
        reference_file = os.path.join(self.output_dir, "reference_solutions", f"{benchmark_id}_swaps.json")

        return os.path.exists(circuit_file) and os.path.exists(metadata_file) and os.path.exists(reference_file)

    def generate_circuit_parameters(self, num_circuits: int = None) -> List[Dict]:
        """Generate the per-instance parameter configurations"""

        # Gate densities: 4 representative points
        gate_densities = [0.2, 0.5, 0.8, 1.0]

        # Size categories
        size_configs = [
            {"size": "S", "depth_range": (20, 50), "samples_per_density": 25},     # 25/density = 100
            {"size": "M", "depth_range": (100, 200), "samples_per_density": 20},   # 20/density = 80
            {"size": "L", "depth_range": (300, 500), "samples_per_density": 15},   # 15/density = 60
            {"size": "XL", "depth_range": (800, 1200), "samples_per_density": 10}  # 10/density = 40
        ]

        parameters = []

        # All parameter combinations
        for size_config in size_configs:
            for density in gate_densities:
                for instance in range(size_config["samples_per_density"]):
                    target_depth = random.randint(*size_config["depth_range"])

                    param = {
                        "size_category": size_config["size"],
                        "target_depth": target_depth,
                        "gate_density": density,
                        "ir_config": IRConfig.default(0.1),
                        "instance_id": instance,
                        "swap_complexity": (random.uniform(0.05, 0.2), random.uniform(0.2, 0.4)),
                        "use_skeleton": True
                    }
                    parameters.append(param)

        # In resume mode, filter out instances that already exist
        if self.resume and self.existing_circuits["total_count"] > 0:
            filtered_params = []
            skipped_count = 0

            for param in parameters:
                benchmark_id = f"{self.target_chip}_{param['size_category']}_d{param['gate_density']:.1f}_{param['instance_id']:03d}"

                if not self.circuit_exists(benchmark_id):
                    filtered_params.append(param)
                else:
                    skipped_count += 1

            print(f"Resume mode: skipping {skipped_count} existing circuits, will generate {len(filtered_params)} new circuits")
            parameters = filtered_params

        # Truncate if a count was requested
        if num_circuits:
            parameters = parameters[:num_circuits]

        return parameters

    def generate_single_benchmark(self, chip_name: str, chip_info: Dict,
                                  params: Dict, benchmark_id: str) -> Optional[Dict]:
        """Generate a single benchmark instance using gate-density control"""
        try:
            print(f"Generating benchmark: {benchmark_id}")
            print(f"  Chip: {chip_name} ({chip_info['num_qubits']} qubits)")
            print(f"  Target depth: {params['target_depth']}, gate density: {params['gate_density']}")

            # Create the QROB generator
            qrob = ReverseSABRE_QROB_with_IR(
                connection_list=chip_info['topology'],
                depth_range=(params['target_depth'], params['target_depth']),
                gate_density=(0.3, 0.7),  # Not used in config mode
                swap_complexity=params['swap_complexity'],
                routing_difficulty=1.0,
                ir_config=params['ir_config'],
                name=f"benchmark_{benchmark_id}"
            )

            # Generate the benchmark in config mode (skeleton-fill + gate density)
            start_time = time.time()

            result = qrob.generate_benchmark(
                mode="config",
                target_depth=params['target_depth'],
                gate_density=params['gate_density']
            )

            generation_time = time.time() - start_time

            # Collect the generated circuits
            original_circuit = qrob.original_circuit  # executable circuit
            qrob_circuit = qrob.circuit  # circuit after SWAP insertion
            confused_circuit = qrob.confused_circuit  # scrambled circuit for routers

            # Convert to Qiskit
            qiskit_original = original_circuit.to_qiskit_circuit_accurate()
            qiskit_qrob = qrob_circuit.to_qiskit_circuit_accurate()
            qiskit_confused = confused_circuit.to_qiskit_circuit_accurate()

            # Check against the targets
            actual_depth = qiskit_original.depth()
            actual_gates = qiskit_original.count_ops().get('cx', 0)

            print(f"  Actual depth: {actual_depth} (target: {params['target_depth']})")
            print(f"  Actual CX gates: {actual_gates}")
            print(f"  Average gates per layer: {actual_gates / actual_depth:.2f}")

            # QASM code
            from qiskit.qasm2.export import dumps
            original_qasm = dumps(qiskit_original)
            confused_qasm = dumps(qiskit_confused)

            # Gate-density metrics
            theoretical_gates_per_layer = int(np.ceil(chip_info['num_qubits'] * params['gate_density'] / 2))
            max_possible_gates_per_layer = chip_info['num_qubits'] // 2
            actual_gates_per_layer = actual_gates / actual_depth if actual_depth > 0 else 0
            density_achievement_ratio = actual_gates_per_layer / max_possible_gates_per_layer if max_possible_gates_per_layer > 0 else 0

            # Initial mapping (identity)
            initial_mapping = {i: i for i in range(chip_info['num_qubits'])}

            # Statistics
            original_depth = qiskit_original.depth()
            original_cx_gates = qiskit_original.count_ops().get('cx', 0)

            qrob_depth = qiskit_qrob.depth()  # depth after SWAP insertion
            qrob_cx_gates = qiskit_qrob.count_ops().get('cx', 0)

            confused_depth = qiskit_confused.depth()
            confused_cx_gates = qiskit_confused.count_ops().get('cx', 0)

            # Reference SWAP sequence
            reference_swap_sequence = []
            for swap_info in qrob.all_repair_swaps:
                swap_gate, layer_idx, gate_idx = swap_info
                reference_swap_sequence.append({
                    'qubits': list(swap_gate),
                    'layer': layer_idx,
                    'position': gate_idx
                })

            # Benchmark record
            benchmark_record = {
                # Identification
                'circuit_id': benchmark_id,
                'chip_name': chip_name,
                'generation_time': generation_time,

                # === Core reference solution ===
                'reference_solution': {
                    'optimal_swap_count': len(qrob.all_repair_swaps),
                    'swap_sequence': reference_swap_sequence,
                    'swap_gates': [list(swap[0]) for swap in qrob.all_repair_swaps]
                },

                # === Original executable circuit ===
                'original_executable_circuit': {
                    'qasm_code': original_qasm,
                    'depth': original_depth,
                    'cx_gate_count': original_cx_gates,
                    'description': "Initial executable circuit before SWAP insertion"
                },

                # === Scrambled circuit (input to routing algorithms) ===
                'benchmark_circuit': {
                    'qasm_code': confused_qasm,
                    'depth': confused_depth,
                    'cx_gate_count': confused_cx_gates,
                    'description': "Circuit to be routed by algorithms"
                },

                # === Gate-density analysis ===
                'gate_density_info': {
                    'target_density': params['gate_density'],
                    'theoretical_gates_per_layer': theoretical_gates_per_layer,
                    'actual_gates_per_layer': actual_gates_per_layer,
                    'max_possible_gates_per_layer': max_possible_gates_per_layer,
                    'density_achievement_ratio': density_achievement_ratio
                },

                # === Depth analysis ===
                'depth_analysis': {
                    'original_depth': original_depth,
                    'qrob_depth': qrob_depth,  # depth after SWAP insertion
                    'confused_depth': confused_depth,  # depth after scrambling
                    'depth_increase': qrob_depth - original_depth,
                    'depth_increase_ratio': (qrob_depth - original_depth) / original_depth if original_depth > 0 else 0
                },

                # === Test setup ===
                'test_setup': {
                    'initial_mapping': initial_mapping,
                    'target_topology': chip_info['topology'],
                    'coupling_map': chip_info['topology']
                },

                # === Generation parameters ===
                'generation_params': {
                    'size_category': params['size_category'],
                    'target_depth': params['target_depth'],
                    'gate_density': params['gate_density'],
                    'actual_depth': actual_depth,
                    'actual_gates': actual_gates,
                    'ir_config_name': params['ir_config'].name,
                    'swap_complexity': params['swap_complexity'],
                    'generation_method': 'skeleton_density'
                },

                # === Chip info ===
                'chip_info': {
                    'num_qubits': chip_info['num_qubits'],
                    'num_edges': chip_info['num_edges'],
                    'topology': chip_info['topology'],
                    'vendor': chip_info['vendor'],
                    'architecture': chip_info['architecture'],
                    'gate_type': chip_info['gate_type']
                },

                # === Routing difficulty analysis ===
                'routing_analysis': {
                    'swap_to_cx_ratio': len(qrob.all_repair_swaps) / max(original_cx_gates, 1),
                    'average_swaps_per_layer': len(qrob.all_repair_swaps) / max(original_depth, 1),
                    'routing_pressure': len(qrob.all_repair_swaps) / max(len(chip_info['topology']), 1),
                    'circuit_complexity_score': original_depth * original_cx_gates
                }
            }

            print(f"Generated successfully:")
            print(f"  Original circuit: depth={original_depth}, CX gates={original_cx_gates}")
            print(f"  QROB circuit: depth={qrob_depth}, CX gates={qrob_cx_gates}")
            print(f"  Reference SWAP count: {len(qrob.all_repair_swaps)}")
            print(f"  Density achievement: {density_achievement_ratio:.2f}")
            print(f"  Depth increase: {qrob_depth - original_depth}")

            return benchmark_record

        except Exception as e:
            print(f"Generation failed {benchmark_id}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def save_benchmark_record(self, record: Dict):
        """Save one benchmark record to disk"""
        circuit_id = record['circuit_id']

        try:
            # Subdirectories
            circuits_dir = os.path.join(self.output_dir, "circuits")
            metadata_dir = os.path.join(self.output_dir, "metadata")
            solutions_dir = os.path.join(self.output_dir, "reference_solutions")

            # Scrambled circuit QASM
            confused_qasm_file = os.path.join(circuits_dir, f"{circuit_id}.qasm")
            with open(confused_qasm_file, 'w', encoding='utf-8') as f:
                f.write(record['benchmark_circuit']['qasm_code'])

            # Original circuit QASM
            original_qasm_file = os.path.join(circuits_dir, f"{circuit_id}_original.qasm")
            with open(original_qasm_file, 'w', encoding='utf-8') as f:
                f.write(record['original_executable_circuit']['qasm_code'])

            # Metadata
            metadata = {k: v for k, v in record.items()
                        if k not in ['benchmark_circuit', 'original_executable_circuit']}
            metadata_file = os.path.join(metadata_dir, f"{circuit_id}.json")
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, default=str)

            # Reference SWAP sequence
            swap_file = os.path.join(solutions_dir, f"{circuit_id}_swaps.json")
            swap_data = {
                'circuit_id': circuit_id,
                'optimal_swap_count': record['reference_solution']['optimal_swap_count'],
                'swap_sequence': record['reference_solution']['swap_sequence'],
                'swap_gates': record['reference_solution']['swap_gates']
            }
            with open(swap_file, 'w', encoding='utf-8') as f:
                json.dump(swap_data, f, indent=2)

            # Append to the record list
            self.benchmark_records.append(record)

        except Exception as e:
            print(f"Save failed: {circuit_id} - {e}")
            raise e

    def generate_single_chip_dataset(self, num_circuits: int = None):
        """Generate the dataset for a single chip"""
        print("=" * 60)
        print(f"Generating benchmark dataset for chip {self.target_chip}")
        print("=" * 60)

        # Load chip data
        chip_data = self.load_chip_data()
        if not chip_data:
            print("No chip data loaded, exiting")
            return

        if self.target_chip not in chip_data:
            print(f"No data found for chip {self.target_chip}")
            return

        chip_info = chip_data[self.target_chip]

        # Generate instance parameters (existing instances filtered automatically)
        circuit_params = self.generate_circuit_parameters(num_circuits)

        if len(circuit_params) == 0:
            print("All circuits already generated, nothing to do!")
            return {
                'chip_name': self.target_chip,
                'total_circuits': 0,
                'successful': 0,
                'failed': 0,
                'total_time': 0
            }

        print(f"Planning to generate {len(circuit_params)} benchmarks for chip {self.target_chip}")
        print(f"Configuration distribution:")
        size_counts = {}
        density_counts = {}
        for p in circuit_params:
            size_counts[p['size_category']] = size_counts.get(p['size_category'], 0) + 1
            density_counts[p['gate_density']] = density_counts.get(p['gate_density'], 0) + 1

        for size, count in sorted(size_counts.items()):
            print(f"  {size}: {count} instances")
        print(f"Gate density distribution: {dict(sorted(density_counts.items()))}")

        # Start generating
        generated_count = 0
        failed_count = 0
        start_time = time.time()

        for i, params in enumerate(circuit_params):
            benchmark_id = f"{self.target_chip}_{params['size_category']}_d{params['gate_density']:.1f}_{params['instance_id']:03d}"

            print(f"\n[{i + 1}/{len(circuit_params)}] Generating: {benchmark_id}")

            # Double-check existence (guards against concurrent generation)
            if self.circuit_exists(benchmark_id):
                print(f"  Circuit already exists, skipping")
                continue

            # Generate the benchmark
            record = self.generate_single_benchmark(self.target_chip, chip_info, params, benchmark_id)

            if record:
                self.save_benchmark_record(record)
                generated_count += 1
            else:
                failed_count += 1

            # Progress report
            if (i + 1) % 10 == 0:
                elapsed = time.time() - start_time
                progress = (i + 1) / len(circuit_params) * 100
                print(f"  Progress: {progress:.1f}% ({i + 1}/{len(circuit_params)}), "
                      f"succeeded: {generated_count}, failed: {failed_count}, elapsed: {elapsed:.1f}s")

        # Save summary data
        if generated_count > 0:
            self.save_summary_data()

        # Final report
        total_time = time.time() - start_time
        print("\n" + "=" * 60)
        print(f"Dataset generation for chip {self.target_chip} complete!")
        print("=" * 60)
        print(f"Total time: {total_time:.1f}s")
        print(f"Generated: {generated_count} benchmarks")
        print(f"Failed: {failed_count}")
        if generated_count + failed_count > 0:
            print(f"Success rate: {generated_count / (generated_count + failed_count) * 100:.1f}%")
        print(f"Output directory: {self.output_dir}")

        return {
            'chip_name': self.target_chip,
            'total_circuits': len(circuit_params),
            'successful': generated_count,
            'failed': failed_count,
            'total_time': total_time
        }

    def save_summary_data(self):
        """Save the summary CSV and complete metadata"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Summary CSV
        csv_file = os.path.join(self.output_dir, f"benchmark_summary_{timestamp}.csv")

        csv_data = []
        for record in self.benchmark_records:
            csv_row = {
                'circuit_id': record['circuit_id'],
                'chip_name': record['chip_name'],
                'vendor': record['chip_info']['vendor'],
                'architecture': record['chip_info']['architecture'],
                'gate_type': record['chip_info']['gate_type'],
                'size_category': record['generation_params']['size_category'],

                # Gate density
                'gate_density': record['generation_params']['gate_density'],
                'target_depth': record['generation_params']['target_depth'],
                'actual_depth': record['generation_params']['actual_depth'],
                'gates_per_layer': record['gate_density_info']['actual_gates_per_layer'],
                'density_achievement': record['gate_density_info']['density_achievement_ratio'],

                # Depth
                'original_depth': record['depth_analysis']['original_depth'],
                'qrob_depth': record['depth_analysis']['qrob_depth'],
                'confused_depth': record['depth_analysis']['confused_depth'],
                'depth_increase': record['depth_analysis']['depth_increase'],
                'depth_increase_ratio': record['depth_analysis']['depth_increase_ratio'],

                # Core metrics
                'reference_swap_count': record['reference_solution']['optimal_swap_count'],
                'cx_gates': record['original_executable_circuit']['cx_gate_count'],
                'swap_to_cx_ratio': record['routing_analysis']['swap_to_cx_ratio'],

                # Generation info
                'generation_time': record['generation_time'],
                'generation_method': record['generation_params']['generation_method'],

                # Chip info
                'num_qubits': record['chip_info']['num_qubits'],
                'num_edges': record['chip_info']['num_edges'],

                # Routing difficulty
                'routing_pressure': record['routing_analysis']['routing_pressure'],
                'circuit_complexity': record['routing_analysis']['circuit_complexity_score']
            }
            csv_data.append(csv_row)

        df = pd.DataFrame(csv_data)
        df.to_csv(csv_file, index=False)
        print(f"Summary CSV saved to: {csv_file}")

        # Complete metadata
        metadata_file = os.path.join(self.output_dir, f"complete_metadata_{timestamp}.json")
        complete_metadata = {
            'generation_timestamp': timestamp,
            'total_circuits': len(self.benchmark_records),
            'target_chip': self.target_chip,
            'benchmark_records': self.benchmark_records
        }

        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(complete_metadata, f, indent=2, default=str)
        print(f"Complete metadata saved to: {metadata_file}")

        # Statistics report
        self.generate_statistics_report(df, timestamp)

    def generate_statistics_report(self, df: pd.DataFrame, timestamp: str):
        """Write a plain-text statistics report"""
        report_file = os.path.join(self.output_dir, f"statistics_report_{timestamp}.txt")

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("Benchmark dataset statistics report\n")
            f.write("=" * 50 + "\n\n")

            f.write(f"Generated at: {timestamp}\n")
            f.write(f"Target chip: {self.target_chip}\n")
            f.write(f"Total circuits: {len(df)}\n\n")

            if len(df) > 0:
                # Distribution by size
                f.write("By circuit size:\n")
                size_counts = df['size_category'].value_counts()
                for size, count in size_counts.items():
                    f.write(f"  {size}: {count} circuits\n")
                f.write("\n")

                # Distribution by gate density
                f.write("By gate density:\n")
                density_counts = df['gate_density'].value_counts()
                for density, count in sorted(density_counts.items()):
                    f.write(f"  {density}: {count} circuits\n")
                f.write("\n")

                # Complexity statistics
                f.write("Circuit complexity statistics:\n")
                f.write(f"  Depth:\n")
                f.write(f"    mean: {df['original_depth'].mean():.1f}\n")
                f.write(f"    range: {df['original_depth'].min():.0f} - {df['original_depth'].max():.0f}\n")

                f.write(f"  CX gates:\n")
                f.write(f"    mean: {df['cx_gates'].mean():.1f}\n")
                f.write(f"    range: {df['cx_gates'].min():.0f} - {df['cx_gates'].max():.0f}\n")

                f.write(f"  SWAPs:\n")
                f.write(f"    mean: {df['reference_swap_count'].mean():.1f}\n")
                f.write(f"    range: {df['reference_swap_count'].min():.0f} - {df['reference_swap_count'].max():.0f}\n")

                f.write(f"  Density achievement:\n")
                f.write(f"    mean: {df['density_achievement'].mean():.3f}\n")
                f.write(f"    range: {df['density_achievement'].min():.3f} - {df['density_achievement'].max():.3f}\n")

                f.write("\nGeneration statistics:\n")
                f.write(f"  Generated: {len(df)} circuits\n")
                f.write(f"  Mean generation time: {df['generation_time'].mean():.2f}s\n")

        print(f"Statistics report saved to: {report_file}")


def main():
    """Entry point with command-line arguments"""
    parser = argparse.ArgumentParser(description='QROB benchmark dataset generator (gate-density version, resume supported)')
    parser.add_argument('--chip', type=str, required=True,
                        help='target chip name (a JSON file in chips/)')
    parser.add_argument('--output', type=str, default='benchmark_dataset',
                        help='output directory (default: benchmark_dataset)')
    parser.add_argument('--num-circuits', type=int, default=None,
                        help='number of circuits to generate (default: full preset configuration)')
    parser.add_argument('--seed', type=int, default=42,
                        help='random seed (default: 42)')
    parser.add_argument('--resume', action='store_true', default=True,
                        help='resume from existing output (default: enabled)')
    parser.add_argument('--no-resume', action='store_true',
                        help='disable resume and start from scratch')

    args = parser.parse_args()

    # Resolve the resume flag
    resume = args.resume and not args.no_resume

    print(f"Starting the benchmark dataset generator (gate-density version)")
    print(f"Target chip: {args.chip}")
    print(f"Output directory: {args.output}")
    print(f"Circuit count: {args.num_circuits if args.num_circuits else 'full preset configuration'}")
    print(f"Random seed: {args.seed}")
    print(f"Resume: {'enabled' if resume else 'disabled'}")

    # Seed the RNGs
    random.seed(args.seed)
    np.random.seed(args.seed)

    # Create the generator for the target chip
    generator = BenchmarkDatasetGenerator(
        output_dir=args.output,
        target_chip=args.chip,
        resume=resume
    )

    try:
        # Generate the dataset
        result = generator.generate_single_chip_dataset(num_circuits=args.num_circuits)

        # Summary
        print(f"\n{args.chip} dataset generation complete!")
        print(f"Succeeded: {result['successful']}, failed: {result['failed']}")
        print(f"Time: {result['total_time']:.1f}s")

        return 0

    except Exception as e:
        print(f"\nError during generation: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
