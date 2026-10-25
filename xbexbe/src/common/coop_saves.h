#pragma once
#include "cpu/x86_ops.h"

// Include the original two-profile CoOp record in the save manager's I/O.
X86_EXTERN_FUNC(sub_000CAE2D);
X86_EXTERN_FUNC(sub_000CAEB0);
X86_EXTERN_FUNC(sub_000CAF4C);
// Do not select a frontend profile page before a queued disk reload completes.
X86_EXTERN_FUNC(sub_000E5613);
