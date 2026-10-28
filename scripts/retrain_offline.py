"""Run a guarded, offline comparison. This script never saves or deploys a model."""
import json

from core.retraining import run_offline_retraining_experiment


if __name__ == "__main__":
    print(json.dumps(run_offline_retraining_experiment(), indent=2))
