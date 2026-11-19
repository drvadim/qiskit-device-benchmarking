"""Run a layer fidelity (LF/EPLG) measurement and CLOPS on the same qubit chain,
submitted back to back so they fall in the same calibration window.

The CLOPS_h definition (arXiv:2608.18044) requires CLOPS to be measured under
layer-fidelity operating conditions (LFOC): the same chain, gates, error
suppression and calibration cycle as the LF measurement it is paired with.

What this script does:
  1. Takes the backend's reported lf_<width> chain (or --qubits) and records the
     backend calibration timestamp.
  2. Submits the LF job and then the CLOPS repeats immediately, before blocking
     on any of them, so the jobs are queued together.
  3. Waits for everything, records the calibration timestamp again, and marks
     the window as "same" only if the timestamp never changed.
  4. Reports LF/EPLG for the chain, the median CLOPS over the repeats and the
     CLOPS report fields, with lfoc_declared set from the window check.

Limitation: the calibration timestamp comes from the backend properties at the
time of the checks, not from the individual jobs, so a calibration that begins
and ends between two checks would not be seen. Treat "same window" as a strong
indication, not a proof.

Example:
    python run_lf_and_clops.py ibm_marrakesh --repeats 3 --out marrakesh_lf_clops.json
"""

import argparse
import json
import statistics
import warnings

from qiskit_ibm_runtime import QiskitRuntimeService

import qiskit_device_benchmarking.utilities.layer_fidelity_utils as lfu
from qiskit_device_benchmarking.clops.clops_benchmark import clops_benchmark


def calibration_stamp(backend):
    """Timestamp of the backend's latest calibration properties (fresh fetch)."""
    return str(backend.properties(refresh=True).last_update_date)


def plain(value):
    """Convert an analysis value (possibly a ufloat) to a JSON-friendly form."""
    if hasattr(value, "nominal_value"):
        return {"value": float(value.nominal_value), "std": float(value.std_dev)}
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def lf_summary(exp_data):
    """Pull the chain-level LF and EPLG results out of the experiment data."""
    df = exp_data.analysis_results(dataframe=True)
    out = {}
    for name in ("LF", "EPLG"):
        rows = df[df["name"] == name]
        if len(rows):
            out[name] = plain(rows.iloc[0]["value"])
    return out


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("backend")
    p.add_argument("--width", type=int, default=100, help="chain length (default 100)")
    p.add_argument("--layers", type=int, default=100, help="CLOPS depth D")
    p.add_argument("--shots", type=int, default=100, help="CLOPS shots per circuit S")
    p.add_argument("--num-circuits", type=int, default=5000, help="CLOPS K")
    p.add_argument("--repeats", type=int, default=3, help="CLOPS repeats (default 3)")
    p.add_argument("--qubits", type=int, nargs="+", help="explicit chain, overrides lf_<width>")
    p.add_argument("--lf-nseeds", type=int, default=6)
    p.add_argument("--lf-nshots", type=int, default=200)
    p.add_argument("--out", default=None, help="JSON output path")
    return p.parse_args()


def main():
    args = parse_args()
    service = QiskitRuntimeService()
    backend = service.backend(args.backend)

    chain = list(args.qubits) if args.qubits else lfu.get_lf_chain(backend, args.width)
    if chain is None:
        raise SystemExit(f"{args.backend} reports no lf_{args.width} chain; pass --qubits")
    if len(chain) != args.width:
        raise SystemExit(f"chain has {len(chain)} qubits but --width is {args.width}")

    stamps = {"before_submit": calibration_stamp(backend)}
    print("Chain:", chain)
    print("Calibration at submit:", stamps["before_submit"])

    # Submit the LF job and all CLOPS repeats back to back, then wait.
    lf_data = lfu.run_lf_chain(
        chain=chain,
        backend=backend,
        nseeds=args.lf_nseeds,
        nshots=args.lf_nshots,
    )
    runs = []
    for i in range(args.repeats):
        runs.append(
            clops_benchmark(
                service,
                args.backend,
                width=args.width,
                layers=args.layers,
                shots=args.shots,
                num_circuits=args.num_circuits,
                qubits=chain,
            )
        )
        print(f"Submitted CLOPS repeat {i + 1}/{args.repeats}: {runs[-1].job.job_id()}")
    stamps["after_submit"] = calibration_stamp(backend)

    lf_data.block_for_results()
    clops_values = [r.clops() for r in runs]
    stamps["after_results"] = calibration_stamp(backend)

    same_window = len(set(stamps.values())) == 1
    chains_match = all(list(r.job_attributes["qubits"]) == chain for r in runs)
    lfoc = bool(same_window and chains_match)

    # lfoc_declared is only known now; fill it in so report() states it.
    # Gates, error suppression and DD are the defaults for both measurements.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for r in runs:
            r.job_attributes["lfoc_declared"] = lfoc
        report = runs[0].report()
    report["clops"] = round(statistics.median(clops_values))

    result = {
        "backend": args.backend,
        "chain": chain,
        "calibration_timestamps": stamps,
        "same_calibration_window": same_window,
        "clops_chain_matches_lf_chain": chains_match,
        "lfoc_declared": lfoc,
        "lf": lf_summary(lf_data),
        "lf_job_ids": list(lf_data.job_ids),
        "clops_runs": [
            {"job_id": r.job.job_id(), "clops": v} for r, v in zip(runs, clops_values)
        ],
        "clops_median": report["clops"],
        "clops_spread_pct": round(
            100 * (max(clops_values) - min(clops_values)) / report["clops"], 2
        ),
        "report": report,
    }

    print(json.dumps({k: v for k, v in result.items() if k not in ("chain", "report")}, indent=2))
    if not same_window:
        print(
            "WARNING: the calibration timestamp changed during the measurement; "
            "the LF and CLOPS results are not in one calibration window. Re-run."
        )
    if args.out:
        with open(args.out, "w") as f:
            json.dump(result, f, indent=2)
        print("Saved", args.out)


if __name__ == "__main__":
    main()
