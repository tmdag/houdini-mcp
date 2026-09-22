"""Code execution handler with dangerous pattern guard."""
import io
import os
import sys
import traceback
from contextlib import redirect_stdout, redirect_stderr

import hou

DANGEROUS_PATTERNS = [
    "hou.exit", "os.remove", "os.unlink", "shutil.rmtree",
    "subprocess", "os.system", "os.popen", "__import__",
]


def _store_last(payload):
    try:
        hou.session.houdinimcp_last = payload
    except Exception:
        pass


def execute_code(code, allow_dangerous=False):
    """Run Python in the Houdini session.

    Never raises to the TCP layer — errors come back as JSON so the MCP
    client can judge the work (stdout/stderr/traceback), not just the
    Houdini console.
    """
    if not allow_dangerous:
        for pattern in DANGEROUS_PATTERNS:
            if pattern in code:
                payload = {
                    "executed": False,
                    "error": "Dangerous pattern %r. Pass allow_dangerous=True." % pattern,
                    "stdout": "",
                    "stderr": "",
                    "traceback": "",
                }
                _store_last(payload)
                return payload
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    try:
        namespace = {"hou": hou}
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            exec(code, namespace)
        payload = {
            "executed": True,
            "stdout": stdout_capture.getvalue(),
            "stderr": stderr_capture.getvalue(),
            "error": None,
            "traceback": "",
        }
        _store_last(payload)
        return payload
    except Exception as e:
        tb = traceback.format_exc()
        payload = {
            "executed": False,
            "error": "%s: %s" % (type(e).__name__, e),
            "stdout": stdout_capture.getvalue(),
            "stderr": stderr_capture.getvalue(),
            "traceback": tb,
        }
        _store_last(payload)
        return payload


def get_last_log():
    """Return the last execute_code / command payload stored on hou.session."""
    return getattr(hou.session, "houdinimcp_last", None) or {
        "executed": None,
        "error": "no log yet",
    }


def execute_hscript(command):
    """Execute an HScript command and return the output."""
    result = hou.hscript(command)
    return {"stdout": result[0], "stderr": result[1]}


def evaluate_expression(expression, language="hscript"):
    """Evaluate a Houdini expression and return the result."""
    if language == "python":
        result = hou.expressionGlobals()
        val = eval(expression, result)
    else:
        val = hou.hscriptExpression(expression)
    return {"expression": expression, "result": str(val), "language": language}


def get_env_variable(name):
    """Get a Houdini environment variable ($HIP, $JOB, etc.)."""
    val = hou.getenv(name)
    return {"name": name, "value": val}
