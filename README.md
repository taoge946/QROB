# QROB

[中文说明 / Chinese version](README_zh.md)

QROB (Quantum Realization Overhead Benchmark) generates quantum-circuit routing
benchmarks with built-in reference solutions. Instead of searching forward for a good
SWAP insertion, it starts from a circuit that already runs on the target coupling map,
scrambles it with recorded SWAPs, and keeps the inverse trajectory as a
compiler-independent reference SWAP count. Both the starting circuit and the
scrambling rule can be customized. Use the benchmarks to measure how far a routing
pass is from a known-feasible cost, or as labeled training data for learned routers.

- Paper (MICRO 2026): *QROB: Quantifying Realization Overhead in Quantum
  Compilation via Reverse Construction* — [arXiv:2609.07776](https://arxiv.org/abs/2609.07776)
- Paper artifact: [DOI 10.5281/zenodo.21539550](https://doi.org/10.5281/zenodo.21539550)

## Install

```bash
pip install -r requirements.txt   # qiskit, networkx, numpy, pandas
```

## Use

Generate one benchmark (see [`examples/`](examples/) for runnable scripts, including
a SABRE comparison):

```python
from QROB import IRConfig, ReverseSABRE_QROB_with_IR, generate_grid_topology

qrob = ReverseSABRE_QROB_with_IR(
    connection_list=generate_grid_topology(4, 4),   # edge list over qubits 0..n-1
    depth_range=(20, 20),
    gate_density=(0.3, 0.7),                        # unused in config mode
    swap_complexity=(0.2, 0.4),
    ir_config=IRConfig.default(0.1),                # influence weighting
)
qrob.generate_benchmark(mode="config", target_depth=20, gate_density=0.5)

benchmark = qrob.confused_circuit.to_qiskit_circuit_accurate()  # route this
reference = len(qrob.all_repair_swaps)                          # against this
```

Generate a suite for one chip (S/M/L/XL sizes x 4 gate densities; 17 chip topologies
in [`chips/`](chips/), or add your own JSON with a `topology` edge list):

```bash
python benchmarkGen.py --chip quafu_baihua --output benchmark_dataset --seed 42
```

`--num-circuits N` generates only the first N instances.

Each instance yields the scrambled circuit (`circuits/<id>.qasm`), the executable
pre-scrambling circuit (`circuits/<id>_original.qasm`), metadata, and the reference
solution (`reference_solutions/<id>_swaps.json`, reference SWAP count in
`optimal_swap_count`). Benchmarks are routing-only: run your router under an identity
initial mapping and compare its added SWAPs against the reference count.

## Customize

QROB's construction is modular: both the starting circuit and the scrambling rule can
be replaced, and the reference solution is recorded during construction either way.
You can therefore build benchmarks to your needs: start from the built-in generator or
from any circuit of your own that runs directly on the coupling map (for example, one
built from the interaction pattern of a target application); use a preset rule for
choosing scrambling SWAPs or define your own; and set the chip topology, size, gate
density and amount of scrambling. See
[`examples/custom_construction.py`](examples/custom_construction.py) for code.

## Citation

```bibtex
@inproceedings{qrob-micro2026,
  title     = {{QROB}: Quantifying Realization Overhead in Quantum Compilation
               via Reverse Construction},
  author    = {Li, Jintao and Li, Kaiqi and Wang, Rui and Zhao, Yilun and
               Huang, Kaixuan and Wang, Ying and Zhang, Jialin and
               Wang, Zheng-An and Sun, Xiaoming and Fan, Heng},
  booktitle = {Proceedings of the 59th IEEE/ACM International Symposium on
               Microarchitecture (MICRO)},
  year      = {2026},
  eprint    = {2609.07776},
  archivePrefix = {arXiv}
}
```

## License

[MIT](LICENSE)
