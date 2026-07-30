# Copyright 2025 Espressif Systems (Shanghai) PTE LTD
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
"""Formatting of Matter PICS item numbers.

The grammar (per the CSA PICS templates): ``<PREFIX>.<side>`` for cluster role,
then ``.F<bit>`` (feature), ``.A<attr>`` (attribute), ``.C<cmd>.Rsp`` (accepted
command), ``.C<cmd>.Tx`` (generated command), ``.E<event>`` (event). Feature and
command/event ids are 2 hex digits; attribute ids are 4 hex digits; all lowercase.
"""

from __future__ import annotations

SERVER = "S"
CLIENT = "C"


def _hex(value: int | str, width: int) -> str:
    n = int(value, 16) if isinstance(value, str) else int(value)
    return f"{n:0{width}x}"


def cluster_role(pics: str, side: str = SERVER) -> str:
    return f"{pics}.{side}"


def feature(pics: str, bit: int, side: str = SERVER) -> str:
    return f"{pics}.{side}.F{_hex(bit, 2)}"


def attribute(pics: str, attr_id: int | str, side: str = SERVER) -> str:
    return f"{pics}.{side}.A{_hex(attr_id, 4)}"


def accepted_command(pics: str, cmd_id: int | str, side: str = SERVER) -> str:
    return f"{pics}.{side}.C{_hex(cmd_id, 2)}.Rsp"


def generated_command(pics: str, cmd_id: int | str, side: str = SERVER) -> str:
    return f"{pics}.{side}.C{_hex(cmd_id, 2)}.Tx"


def event(pics: str, event_id: int | str, side: str = SERVER) -> str:
    return f"{pics}.{side}.E{_hex(event_id, 2)}"


def client_tx_command(pics: str, cmd_id: int | str) -> str:
    """A command the CLIENT transmits (the server's accepted command)."""
    return f"{pics}.{CLIENT}.C{_hex(cmd_id, 2)}.Tx"
