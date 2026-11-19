import json
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_device_benchmarking.clops.clops_benchmark import clops_benchmark
service = QiskitRuntimeService()
runs = [clops_benchmark(service, "ibm_marrakesh", layers=50, shots=100, num_circuits=5000) for _ in range(3)]
for r in runs: print("submitted", r.job.job_id(), flush=True)
out = []
for r in runs:
    row = {"job_id": r.job.job_id(), "clops": r.clops()}
    out.append(row); print(row, flush=True)
json.dump(out, open("/tmp/clops_sweep/repeat_d50.json", "w"), indent=1)
print("DONE")
