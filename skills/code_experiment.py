"""
Code Experiment Skill — Generate and run reproducible computational experiments.

Provides templates for common scientific experiment types and integrates
with the sandbox executor to ensure isolation and provenance.
"""
import hashlib
import json
import re
import time
from pathlib import Path

import structlog

from sandbox.executor import SandboxExecutor

log = structlog.get_logger()

EXPERIMENTS_DIR = Path("data/experiments")
EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)


class CodeExperimentSkill:
    """Generate, execute, and track computational experiments."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.executor = SandboxExecutor(self.config)

    async def run_experiment(
        self,
        hypothesis: str,
        code: str,
        language: str = "python",
        inputs: dict | None = None,
    ) -> dict:
        """
        Execute an experiment in the sandbox and record its provenance.

        Returns a dict with:
        - experiment_id (SHA-256 of code+inputs)
        - success
        - stdout, stderr
        - result_files
        - provenance_path
        """
        experiment_id = self._compute_id(code, inputs)
        log.info("experiment.starting", experiment_id=experiment_id, hypothesis=hypothesis[:80])

        result = await self.executor.execute(code, language=language)
        executed_code = code
        repair = {
            "attempted": False,
            "succeeded": False,
            "reason": None,
            "original_stderr": result.get("stderr", ""),
        }
        attempts = [{"success": result.get("success"), "stderr": result.get("stderr", "")}]
        if language == "python" and not result.get("success"):
            repaired = self._repair_python_code(code, result.get("stderr", ""))
            if repaired is not None and repaired["code"] != code:
                repair["attempted"] = True
                repair["reason"] = repaired["reason"]
                repaired_result = await self.executor.execute(repaired["code"], language=language)
                attempts.append({
                    "success": repaired_result.get("success"),
                    "stderr": repaired_result.get("stderr", ""),
                })
                if repaired_result.get("success"):
                    result = repaired_result
                    executed_code = repaired["code"]
                    repair["succeeded"] = True

        provenance = {
            "experiment_id": experiment_id,
            "hypothesis": hypothesis,
            "timestamp": time.time(),
            "language": language,
            "code": code,
            "executed_code": executed_code,
            "inputs": inputs or {},
            "success": result.get("success"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "return_code": result.get("return_code"),
            "result_files": result.get("result_files", {}),
            "repair": repair,
            "attempts": attempts,
        }

        prov_path = EXPERIMENTS_DIR / f"{experiment_id}.json"
        prov_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")

        log.info(
            "experiment.complete",
            experiment_id=experiment_id,
            success=result.get("success"),
            provenance=str(prov_path),
        )

        return {
            "experiment_id": experiment_id,
            **result,
            "provenance_path": str(prov_path),
            "repair": repair,
        }

    def _compute_id(self, code: str, inputs: dict | None) -> str:
        payload = json.dumps({"code": code, "inputs": inputs or {}}, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def _repair_python_code(self, code: str, stderr: str) -> dict | None:
        """Repair narrow, common LLM code-generation errors and re-run once."""
        if "Unknown format code 'd' for object of type 'float'" in stderr:
            repaired = re.sub(r"\{([^{}\n:]+):(?:\d*)d\}", r"{\1:.0f}", code)
            return {"code": repaired, "reason": "float_integer_format"}

        if "unterminated f-string literal" in stderr:
            line_match = re.search(r"Line\s+(\d+):", stderr)
            if not line_match:
                return None
            line_no = int(line_match.group(1))
            lines = code.splitlines()
            idx = line_no - 1
            if idx < 0 or idx >= len(lines):
                return None
            bad_line = lines[idx]
            if "f'" not in bad_line and 'f"' not in bad_line:
                return None
            indent = bad_line[: len(bad_line) - len(bad_line.lstrip())]
            lines[idx] = indent + "print('[repair] omitted unterminated generated f-string output line')"
            return {"code": "\n".join(lines) + "\n", "reason": "unterminated_fstring_line"}

        if "unexpected indent" in stderr:
            repaired = self._repair_misaligned_docstring_indent(code)
            if repaired is not None:
                return {"code": repaired, "reason": "misaligned_docstring_indent"}

        return None

    @staticmethod
    def _repair_misaligned_docstring_indent(code: str) -> str | None:
        lines = code.splitlines()
        for i, line in enumerate(lines[:-1]):
            stripped = line.strip()
            if not (stripped.startswith("def ") and stripped.endswith(":")):
                continue
            def_indent_len = len(line) - len(line.lstrip())
            expected_indent = " " * (def_indent_len + 4)
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j >= len(lines):
                continue
            body = lines[j]
            body_stripped = body.lstrip()
            if not (body_stripped.startswith('"""') or body_stripped.startswith("'''")):
                continue
            if body.startswith(expected_indent):
                continue
            candidate_lines = list(lines)
            candidate_lines[j] = expected_indent + body_stripped
            candidate = "\n".join(candidate_lines) + "\n"
            try:
                compile(candidate, "<repaired_experiment>", "exec")
            except SyntaxError:
                continue
            return candidate
        return None

    def build_ode_simulation(
        self,
        description: str,
        ode_func: str,
        y0: list[float],
        t_span: tuple[float, float],
        t_eval_count: int = 100,
        params: dict | None = None,
    ) -> str:
        """
        Build a self-contained Python script for ODE simulation using SciPy.

        ode_func should be a valid Python expression using y (vector) and t,
        e.g. "[-0.5 * y[0], 0.5 * y[0] - 0.1 * y[1]]"
        """
        params_code = "\n".join(f"{k} = {v!r}" for k, v in (params or {}).items())
        return f"""import numpy as np
from scipy.integrate import solve_ivp
import json

# Parameters
{params_code}

# ODE system
def ode(t, y):
    return {ode_func}

y0 = {y0}
t_span = {t_span}
t_eval = np.linspace(t_span[0], t_span[1], {t_eval_count})

sol = solve_ivp(ode, t_span, y0, t_eval=t_eval, method='RK45')

results = {{
    "t": sol.t.tolist(),
    "y": sol.y.tolist(),
    "success": sol.success,
    "message": sol.message,
}}

print(json.dumps(results, indent=2))
with open("ode_results.json", "w") as f:
    json.dump(results, f, indent=2)
"""

    def build_statistical_test(
        self,
        description: str,
        test_type: str,
        sample_a: list[float],
        sample_b: list[float] | None = None,
        alpha: float = 0.05,
    ) -> str:
        """
        Build a self-contained Python script for common statistical tests.
        test_type: 't_test_ind', 't_test_rel', 'mannwhitney', 'wilcoxon', 'anova'
        """
        if test_type == "t_test_ind":
            import_code = "from scipy import stats"
            test_code = f"""stat, pvalue = stats.ttest_ind(sample_a, sample_b)
effect_size = (np.mean(sample_a) - np.mean(sample_b)) / np.sqrt((np.var(sample_a, ddof=1) + np.var(sample_b, ddof=1)) / 2)
result = {{"test": "independent t-test", "statistic": float(stat), "pvalue": float(pvalue), "effect_size": float(effect_size)}}"""
        elif test_type == "t_test_rel":
            import_code = "from scipy import stats"
            test_code = f"""stat, pvalue = stats.ttest_rel(sample_a, sample_b)
d = np.mean(np.array(sample_a) - np.array(sample_b)) / np.std(np.array(sample_a) - np.array(sample_b), ddof=1)
result = {{"test": "paired t-test", "statistic": float(stat), "pvalue": float(pvalue), "effect_size": float(d)}}"""
        elif test_type == "mannwhitney":
            import_code = "from scipy import stats"
            test_code = f"""stat, pvalue = stats.mannwhitneyu(sample_a, sample_b, alternative='two-sided')
result = {{"test": "Mann-Whitney U", "statistic": float(stat), "pvalue": float(pvalue)}}"""
        elif test_type == "wilcoxon":
            import_code = "from scipy import stats"
            test_code = f"""stat, pvalue = stats.wilcoxon(sample_a, sample_b)
result = {{"test": "Wilcoxon signed-rank", "statistic": float(stat), "pvalue": float(pvalue)}}"""
        elif test_type == "anova":
            import_code = "from scipy import stats"
            groups = sample_a if isinstance(sample_a, list) and isinstance(sample_a[0], list) else [sample_a]
            groups_literal = str(groups)
            test_code = f"""groups = {groups_literal}
stat, pvalue = stats.f_oneway(*groups)
result = {{"test": "one-way ANOVA", "statistic": float(stat), "pvalue": float(pvalue), "groups": len(groups)}}"""
        else:
            import_code = "from scipy import stats"
            test_code = "result = {'error': 'unknown test type'}"

        sample_b_literal = str(sample_b) if sample_b is not None else "None"
        return f"""import numpy as np
{import_code}
import json

sample_a = {sample_a}
sample_b = {sample_b_literal}
alpha = {alpha}

{test_code}

result["alpha"] = alpha
result["significant"] = result.get("pvalue", 1.0) < alpha

print(json.dumps(result, indent=2))
with open("stat_test_results.json", "w") as f:
    json.dump(result, f, indent=2)
"""

    def build_regression_analysis(
        self,
        description: str,
        X: list[list[float]],
        y: list[float],
        model_type: str = "linear",
    ) -> str:
        """Build a self-contained Python script for linear regression using numpy."""
        return f"""import numpy as np
import json

X = np.array({X})
y = np.array({y})

# Ordinary least squares: beta = (X^T X)^{{-1}} X^T y
beta = np.linalg.pinv(X.T @ X) @ X.T @ y
predictions = X @ beta
ss_res = np.sum((y - predictions) ** 2)
ss_tot = np.sum((y - np.mean(y)) ** 2)
r2 = 1 - ss_res / ss_tot if ss_tot != 0 else 0.0
mse = ss_res / len(y)

result = {{
    "model_type": "{model_type}",
    "r2_score": float(r2),
    "mse": float(mse),
    "coefficients": beta.tolist() if hasattr(beta, 'tolist') else float(beta),
}}

print(json.dumps(result, indent=2))
with open("regression_results.json", "w") as f:
    json.dump(result, f, indent=2)
"""
