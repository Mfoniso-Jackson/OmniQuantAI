from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from omniquantai.application.competition import run_competition_playbook
from omniquantai.configuration.settings import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OmniQuantAI competition performance playbook.")
    parser.add_argument(
        "--output-dir",
        default="artifacts/competition",
        help="Directory for decision and AI-log evidence artifacts.",
    )
    args = parser.parse_args()

    report = run_competition_playbook(Path(args.output_dir), load_settings())

    print("OmniQuantAI Competition Playbook")
    print("-" * 34)
    print(f"Mode: {report.mode}")
    print(f"Recommendation: {report.recommendation}")
    print(f"Trades: {report.performance.trade_count}")
    print(f"Ending equity: {report.performance.ending_equity}")
    print(f"Total return: {report.performance.total_return}")
    print(f"Max drawdown: {report.performance.max_drawdown}")
    print(f"Decision log: {report.decision_log_path}")
    print(f"AI log: {report.ai_log_path}")
    print("Gates:")
    for gate in report.gates:
        gate_payload = asdict(gate)
        print(f"- {gate_payload['status'].upper()} {gate_payload['name']}: {gate_payload['detail']}")


if __name__ == "__main__":
    main()

