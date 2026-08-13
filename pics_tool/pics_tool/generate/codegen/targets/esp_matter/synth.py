# Copyright 2026 Espressif Systems (Shanghai) PTE LTD
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Generic argument synthesizer -- the scalability core of the esp_matter target.

Given a resolved :class:`~...knowledge.Signature`, bind a value for every
parameter AFTER the receiver from ONE additive rule table keyed on the param's
C++ type. New API surface = a param captured in the signature index; a new
argument *kind* = one new rule here. Anything unrecognized degrades to a flagged
``/* <type> */`` placeholder, so we compile-or-flag but never emit wrong code.
"""

from __future__ import annotations

import re

_INT_RE = re.compile(r"^u?int(?:8|16|32|64)_t$")
_NULLABLE_RE = re.compile(r"^nullable<(?P<inner>.+)>$")
_TYPEISH_RE = re.compile(r"^[A-Za-z_][\w:]*(?:<.*>)?$")


def value_for(type_str: str) -> str:
    """A compiling default value expression for a non-config, non-pointer type."""
    base = re.sub(r"^const\s+", "", type_str.strip()).rstrip("&").strip()
    if base == "bool":
        return "false"
    if _INT_RE.match(base):
        return "0"
    if base in ("float", "double"):
        return "0"
    m = _NULLABLE_RE.match(base)
    if m:
        return f"nullable<{m.group('inner').strip()}>()"
    if _TYPEISH_RE.match(base):
        # enum / value type: value-initialize (0 for enums/arithmetic, default ctor).
        return f"{base}{{}}"
    return f"/* {type_str.strip()} */"


def build_call(sig, symbol: str, var_base: str, n: int) -> tuple[list[str], list[str]]:
    """Return (decl_lines, arg_exprs) for the params AFTER the receiver (param 0).

    ``config_t*`` params get a declared config struct (esp_matter defaults) and are
    passed by address; other params get a synthesized default value.
    """
    ns = symbol.rsplit("::", 1)[0]
    decls: list[str] = []
    args: list[str] = []
    for i, p in enumerate(sig.params):
        if i == 0:
            continue  # the receiver (cluster_t*/endpoint_t*/...)
        t = p.type.strip()
        is_ptr = t.endswith("*")
        base = t[:-1].strip() if is_ptr else t
        if is_ptr and (base == "config_t" or base.endswith("::config_t")):
            qualified = f"{ns}::config_t" if base == "config_t" else base
            var = f"{var_base}_config_{n}"
            decls.append(f"{qualified} {var};")
            args.append(f"&{var}")
        elif is_ptr:
            args.append("nullptr")  # non-config pointer/delegate: user must wire it
        else:
            args.append(value_for(t))
    return decls, args
