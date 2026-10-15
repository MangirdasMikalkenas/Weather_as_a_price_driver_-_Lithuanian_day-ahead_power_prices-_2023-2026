"""
Do the engine tests catch errors? Plants one error at a time in a copy of src/ and runs the engine tests on it.

Each planted error changes the results without crashing anything: a history window that looks a day ahead, a stale
volatility, log changes applied as absolute ones, a missing post-shock lower bound and so on. A test suite that still
passed on such a copy would not have noticed the error.

Run:  python tests/check_mutations.py   (about a minute and a half)
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ["tests/test_risk_engines.py", "tests/test_bank_products.py", "tests/test_exposure.py",
         "tests/test_backtests.py"]
MUTATIONS = [   # file in src/, the code, the code with the error, the error
    ("risk_engines.py", "return np.arange(t - 1 - window, t - 1)", "return np.arange(t - window, t)",
     "the VaR history includes the change of the day being forecast"),
    ("risk_engines.py", "today = {name: levels[name][t - 1] for name in levels}",
     "today = {name: levels[name][t] for name in levels}",
     "scenarios applied to the market of the forecast day instead of the day before"),
    ("risk_engines.py", "volatility_scaled(changes[name], scale[name], rows, t - 1)",
     "volatility_scaled(changes[name], scale[name], rows, t - 2)",
     "filtered scenarios rescaled to a volatility forecast one day stale"),
    ("risk_engines.py", "        return level * np.exp(changes)", "        return level + changes",
     "log changes of a price applied as absolute changes"),
    ("risk_engines.py", "        h = t - lag + 1 ", "        h = t - lag + 2 ",
     "the CFaR history includes a day not yet known at the time of the forecast"),
    ("risk_engines.py", "scale = 1.0 if sigma is None else sigma[h]", "scale = 1.0 if sigma is None else sigma[h - 1]",
     "the filtered CFaR rescaled to a volatility forecast one day stale"),
    ("risk_engines.py", "starts = np.arange(0, end - length + 1, step)", "starts = np.arange(0, end + 1, step)",
     "the stress-window search looks past its review date"),
    ("risk_engines.py", "rows = part[:, None] - 1 - window + np.arange(window)",
     "rows = part[:, None] - window + np.arange(window)",
     "the rolling VaR of the simulated histories includes the change of the day being forecast"),
    ("backtests.py", "only_b = int(np.sum(a & ~b)), int(np.sum(b & ~a))",
     "only_b = int(np.sum(a & ~b)), int(np.sum(b))",
     "the paired test counts every exception of the second model, not only the days without one of the first"),
    ("bank_products.py", "present_value(liabilities, rate_at) + hedge", "present_value(liabilities, rate_at) - hedge",
     "the banking-book hedge enters EVE with the wrong sign"),
    ("bank_products.py", "return lambda t: shocked_rates(base_rate(t), t, supervisory_shocks(t, sizes)[scenario])",
     "return lambda t: base_rate(t) + supervisory_shocks(t, sizes)[scenario]",
     "the post-shock lower bound left out"),
    ("exposure.py", "* np.sqrt(days_per_year) * tenor / b,", "* np.sqrt(days_per_year) / b,",
     "the calibration ignores the tenor of the rate it is fitted to"),
    ("exposure.py", "np.quantile(exposure, quantile, axis=0)", "np.quantile(values, quantile, axis=0)",
     "PFE taken from the values instead of the positive exposure"),
    ("exposure.py", "- foreign_rate - 0.5 * sigma ** 2", "- foreign_rate",
     "the FX simulation drops the -sigma^2/2 drift correction"),
    ("exposure.py", "np.sum(effective[1:] * np.diff(t))", "np.sum(effective[:-1] * np.diff(t))",
     "effective EPE sums effective EE at the start of each step, not at its end as CRR Art. 284(6) does"),
]


def main():
    missed = 0
    for file, code, mutated, error in MUTATIONS:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp)
            for folder in ("src", "tests"):
                shutil.copytree(ROOT / folder, copy / folder, ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copy(ROOT / "pytest.ini", copy)
            path = copy / "src" / file
            text = path.read_text(encoding="utf-8")
            if text.count(code) != 1:
                sys.exit(f"src/{file} no longer contains this code once: {code}")
            path.write_text(text.replace(code, mutated), encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS],
                                    cwd=copy, capture_output=True, text=True)
        caught = result.returncode == 1                  # pytest: 1 = some tests failed, 0 = all passed
        if result.returncode not in (0, 1):
            sys.exit(f"pytest could not run ({error}):\n{result.stdout}{result.stderr}")
        missed += not caught
        failing = sum(line.startswith("FAILED") for line in result.stdout.splitlines())
        print(f"{'caught' if caught else 'MISSED'}  {error}" + (f" (failing tests: {failing})" if caught else ""))
    print(f"{len(MUTATIONS) - missed} of {len(MUTATIONS)} planted errors caught")
    sys.exit(1 if missed else 0)


if __name__ == "__main__":
    main()
