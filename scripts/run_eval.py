"""Run the evaluation harness against the golden dataset.

Usage:
    python -m scripts.run_eval
    python -m scripts.run_eval --k 5 --ragas
    python -m scripts.run_eval --out eval_report.json
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.eval.runner import evaluate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5, help="top-K used for retrieval metrics")
    ap.add_argument("--ragas", action="store_true", help="also run Ragas evaluation (slow)")
    ap.add_argument("--out", type=str, default=None, help="write full JSON report to this path")
    args = ap.parse_args()

    summary = evaluate(k=args.k)

    print("\n=== Aggregate metrics ===")
    for k_, v in summary.as_dict().items():
        if isinstance(v, float):
            print(f"  {k_:24s} {v:.3f}")
        elif isinstance(v, dict):
            print(f"  {k_}:")
            for kk, vv in v.items():
                print(f"     - {kk:18s} {vv:.1f} ms")
        else:
            print(f"  {k_:24s} {v}")

    print("\n=== Per-item results ===")
    for it in summary.items:
        print(
            f"  [{'OK' if it.execution_match else ' .'}] "
            f"R@k={it.recall_at_k:.2f}  "
            f"P@k={it.precision_at_k:.2f}  "
            f"hall={'Y' if it.hallucinated else 'N'}  "
            f"{it.question}"
        )

    payload: dict = {"summary": summary.as_dict(), "items": [asdict(i) for i in summary.items]}

    if args.ragas:
        from app.eval.ragas_eval import run_ragas
        print("\nRunning Ragas (this can take a while)...")
        ragas_scores = run_ragas(summary.items)
        payload["ragas"] = ragas_scores
        print("Ragas:", json.dumps(ragas_scores, indent=2, default=str))

    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2, default=str))
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
