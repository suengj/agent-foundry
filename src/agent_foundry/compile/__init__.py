"""Work Item compiler — Task Toolkit + ExecutionBundle."""

from agent_foundry.compile.api import (
    CompileError,
    CompileResult,
    compile_work_item,
)
from agent_foundry.compile.authority import (
    CompileAuthorityError,
    compute_compiled_authority,
    validate_execution_bundle_authority,
)
from agent_foundry.compile.role_assurance import (
    compile_operating_model,
    compile_role_assurance,
    validate_compilation_explainability,
)

__all__ = [
    "CompileAuthorityError",
    "CompileError",
    "CompileResult",
    "compile_work_item",
    "compile_operating_model",
    "compile_role_assurance",
    "compute_compiled_authority",
    "validate_execution_bundle_authority",
    "validate_compilation_explainability",
]
