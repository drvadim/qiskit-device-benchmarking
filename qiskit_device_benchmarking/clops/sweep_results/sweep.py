import json, time, traceback
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_device_benchmarking.clops.clops_benchmark import clops_benchmark

BACKEND = "ibm_marrakesh"
# (name, K=num_circuits, D=layers, S=shots)
POINTS = [
    ("canonical", 5000, 100, 100),
    ("K=2500", 2500, 100, 100),
    ("K=10000", 10000, 100, 100),
    ("S=10", 5000, 100, 10),
    ("D=25", 5000, 25, 100),
    ("D=50", 5000, 50, 100),
    ("D=200", 5000, 200, 100),
]
service = QiskitRuntimeService()
runs = []
for name, K, D, S in POINTS:  # submit everything first, then collect
    try:
        b = clops_benchmark(service, BACKEND, layers=D, shots=S, num_circuits=K)
        runs.append((name, K, D, S, b))
        print("submitted", name, b.job.job_id(), flush=True)
    except Exception:
        traceback.print_exc()
        runs.append((name, K, D, S, None))

results = []
for name, K, D, S, b in runs:
    row = {"name": name, "K": K, "D": D, "S": S}
    try:
        row["job_id"] = b.job.job_id()
        row["clops"] = b.clops()
    except Exception as e:
        row["error"] = repr(e)
    results.append(row)
    print(row, flush=True)
    json.dump(results, open("/tmp/clops_sweep/results.json", "w"), indent=1)
print("DONE")
