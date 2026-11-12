# QROB（中文说明）

[English version](README.md)

QROB（Quantum Realization Overhead Benchmark）用于生成自带参考解的量子电路路由基准。它不做正向搜索，而是反向构造：从一个在目标耦合图上可直接执行的电路出发，用有记录的 SWAP 把它打乱，保留逆轨迹作为与编译器无关的参考 SWAP 数。起点电路和打乱方式都可以自定义。生成的基准可用来度量路由算法离一个已知可行代价有多远，也可作为学习型路由器的带标签训练数据。

- 论文（MICRO 2026）：*QROB: Quantifying Realization Overhead in Quantum Compilation via Reverse Construction* — [arXiv:2609.07776](https://arxiv.org/abs/2609.07776)
- 论文 artifact：[DOI 10.5281/zenodo.21539550](https://doi.org/10.5281/zenodo.21539550)

## 安装

```bash
pip install -r requirements.txt   # qiskit, networkx, numpy, pandas
```

## 使用

生成单个基准（可运行示例见 [`examples/`](examples/)，含与 SABRE 的对比脚本）：

```python
from QROB import IRConfig, ReverseSABRE_QROB_with_IR, generate_grid_topology

qrob = ReverseSABRE_QROB_with_IR(
    connection_list=generate_grid_topology(4, 4),   # 比特编号为 0..n-1 的边表
    depth_range=(20, 20),
    gate_density=(0.3, 0.7),                        # config 模式下不使用
    swap_complexity=(0.2, 0.4),
    ir_config=IRConfig.default(0.1),                # 影响加权
)
qrob.generate_benchmark(mode="config", target_depth=20, gate_density=0.5)

benchmark = qrob.confused_circuit.to_qiskit_circuit_accurate()  # 给路由器的输入
reference = len(qrob.all_repair_swaps)                          # 参考 SWAP 数
```

为某块芯片生成一套基准（S/M/L/XL 四档规模 × 4 档门密度；[`chips/`](chips/) 内置 17 个拓扑，也可自带 `topology` 边表 JSON）：

```bash
python benchmarkGen.py --chip quafu_baihua --output benchmark_dataset --seed 42
```

`--num-circuits N` 只生成前 N 个实例。

每个实例输出：打乱后的电路（`circuits/<id>.qasm`）、打乱前的可执行电路（`circuits/<id>_original.qasm`）、元数据，以及参考解（`reference_solutions/<id>_swaps.json`，参考 SWAP 数在 `optimal_swap_count` 字段）。基准为纯路由任务：在恒等初始映射下运行你的路由器，将其新增 SWAP 数与参考值比较即可。

## 自定义

QROB 的构造是模块化的：起点电路和打乱规则都可以替换，而参考解始终在构造过程中记录下来。因此可以按需要构造基准：起点可以用内置生成器，也可以是你自己搭的任意一个在耦合图上可直接执行的电路（比如按某类应用的相互作用结构搭建）；打乱时挑选 SWAP 的规则可以用预置的，也可以自己定义；芯片拓扑、规模、门密度和打乱程度也都可以设定。示例代码见 [`examples/custom_construction.py`](examples/custom_construction.py)。

## 引用

见 [README.md](README.md) 中的 BibTeX。

## 许可证

[MIT](LICENSE)
