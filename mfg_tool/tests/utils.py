#!/usr/bin/env python3

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

import subprocess
import logging
from dataclasses import dataclass
from typing import List
import shlex

logger = logging.getLogger(__name__)


@dataclass
class Config:
    """Configuration for individual test case
    Test case json is converted into this class object for easier access and validation
    This class object is then used to run the test case and validate the output

    Args:
        description: Description of the test case
        command: Command to run the test case
        expected_output: Expected output of the test case
        validate_cert: Whether to validate the certificates generated from the test case output
        validate_path: Whether to validate the output paths generated from the test case output
        validate_no_bin: Whether to validate that no binary partition files are generated from the test case output
        validate_secure_cert: Whether to validate that secure cert partition files are generated from the test case output
        validate_no_secure_cert_bin: Whether to validate that no secure cert partition files are generated from the test case output
    """

    description: str
    command: str
    expected_output: str
    validate_cert: bool = False
    validate_cn_in_path: bool = False
    validate_cn_not_in_path: bool = False
    validate_no_bin: bool = False
    validate_csv_quoting: bool = False
    validate_secure_cert: bool = False
    validate_no_secure_cert_bin: bool = False
    validate_partition_bin: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """
        Convert test case json into Config class object
        This is used to run the test case and validate the output
        This is class method to allow for easy conversion from json to Config class object

        Args:
            data: Test case json

        Returns:
            Config: Config class object
        """
        return cls(
            description=data.get("description", ""),
            command=data.get("command", ""),
            expected_output=data.get("expected_output", ""),
            validate_cert=data.get("validate_cert", False),
            validate_cn_in_path=data.get("validate_cn_in_path", False),
            validate_cn_not_in_path=data.get("validate_cn_not_in_path", False),
            validate_no_bin=data.get("validate_no_bin", False),
            validate_csv_quoting=data.get("validate_csv_quoting", False),
            validate_secure_cert=data.get("validate_secure_cert", False),
            validate_no_secure_cert_bin=data.get("validate_no_secure_cert_bin", False),
            validate_partition_bin=data.get("validate_partition_bin", False),
        )


@dataclass
class ParsedOutput:
    """Parsed output of the esp-matter-mfg-tool command"""

    out_path: str = ""
    dac_cert: str = ""
    dac_key: str = ""
    dac_pub_key: str = ""
    pai_cert: str = ""
    secure_cert_bin: str = ""
    partition_bin: str = ""


def run_command(command):
    """Run a command and capture output"""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=60
        )
        return result
    except subprocess.TimeoutExpired as e:
        logger.error(f"Command timed out: {e}")
        return e


def parse_mfg_tool_output(output: str) -> List[ParsedOutput]:
    """Parse the output of the esp-matter-mfg-tool command"""

    def get_uuid_from_path(path: str) -> str:
        import os

        return os.path.basename(path)

    parsed_output = []

    for line in output.split("\n"):
        if "Generated output files at:" in line:
            out_path = line.split("Generated output files at: ")[1].strip()

            uuid_dir = get_uuid_from_path(out_path)
            secure_cert_bin_path = f"{out_path}/{uuid_dir}_esp_secure_cert.bin"
            partition_bin_path = f"{out_path}/{uuid_dir}-partition.bin"

            parsed_output.append(
                ParsedOutput(
                    out_path=out_path,
                    dac_cert=f"{out_path}/internal/DAC_cert.der",
                    dac_key=f"{out_path}/internal/DAC_key.der",
                    dac_pub_key=f"{out_path}/internal/DAC_public_key.bin",
                    pai_cert=f"{out_path}/internal/PAI_cert.der",
                    secure_cert_bin=secure_cert_bin_path,
                    partition_bin=partition_bin_path,
                )
            )

    return parsed_output


def any_base_int(val):
    try:
        return int(val, 0)
    except ValueError:
        return val


def normalize_key(token):
    SHORT_TO_LONG = {
        "-v": "vendor-id",
        "-p": "product-id",
        "-c": "cert",
        "-k": "key",
        "-cd": "cert-dclrn",
        "-cn": "cn-prefix",
        "-dm": "discovery-mode",
        "-cf": "commissioning-flow",
        "-ds": "ds-peripheral",
        "-lt": "lifetime",
        "-vf": "valid-from",
        "-n": "count",
        "-s": "size",
        "-e": "encrypt",
    }
    if token.startswith("--"):
        return token[2:]

    if token in SHORT_TO_LONG:
        return SHORT_TO_LONG[token]

    return token.lstrip("-")


def parse_command_arguments(command: str) -> dict:
    tokens = shlex.split(command)

    if tokens and not tokens[0].startswith("-"):
        tokens = tokens[1:]

    result = {}
    i = 0

    while i < len(tokens):
        token = tokens[i]

        if token.startswith("-"):
            key = normalize_key(token)

            values = []
            j = i + 1

            while j < len(tokens):
                next_token = tokens[j]

                if next_token.startswith("-") and not next_token.lstrip("-").isdigit():
                    break

                values.append(any_base_int(next_token))
                j += 1

            if not values:
                value = True
            elif len(values) == 1:
                value = values[0]
            else:
                value = values

            if key in result:
                if not isinstance(result[key], list):
                    result[key] = [result[key]]
                if isinstance(value, list):
                    result[key].extend(value)
                else:
                    result[key].append(value)
            else:
                result[key] = value

            i = j
        else:
            i += 1

    return result


def parse_partition_bin(partition_bin_path: str) -> dict:
    """
    Parse NVS partition binary and extract chip-factory namespace data

    Args:
        partition_bin_path: Path to partition binary file

    Returns:
        dict: Dictionary with namespace data, format: {namespace: {key: (type, value)}}
    """
    from enum import Enum

    # NVS Constants
    PAGE_SIZE = 4096
    PSB_INIT = 0x01
    PSB_FREE = 0x04
    PSB_CORRUPT = 0x08
    ESB_WRITTEN = 0x01
    ESB_ERASED = 0x02
    ESB_OFFSET = 32
    ESB_LENGTH = 32
    ENTRY_0_OFFSET = 64
    ENTRY_LENGTH = 32

    # Entry field offsets
    NS_OFFSET = 0
    TYPE_OFFSET = 1
    SPAN_OFFSET = 2
    CHUNK_IDX_OFFSET = 3
    KEY_OFFSET = 8
    KEY_LENGTH = 16
    DATA_OFFSET = 24

    class EntryState(Enum):
        UNUSED = 1
        WRITTEN = 2
        ERASED = 3

    class EntryType(Enum):
        U8 = 0x01
        I8 = 0x11
        U16 = 0x02
        I16 = 0x12
        U32 = 0x04
        I32 = 0x14
        U64 = 0x08
        I64 = 0x18
        STR = 0x21
        BLOB = 0x42
        BLOB_IDX = 0x48

    class BlobReassembly:
        def __init__(self):
            self.size = 0
            self.chunk_count = 0
            self.chunk_start = 0
            self.chunks = []

        def add_chunk(self, chunk_index, data):
            self.chunks.append((chunk_index, data))

        def add_blob_index_info(self, size, chunk_count, chunk_start):
            self.size = size
            self.chunk_count = chunk_count
            self.chunk_start = chunk_start

        def get_reassembled_blob(self):
            if self.size == 0:
                return bytearray()
            self.chunks.sort(key=lambda x: x[0])
            blob_data = bytearray()
            for chunk in self.chunks:
                blob_data.extend(chunk[1])
            return blob_data

    with open(partition_bin_path, "rb") as f:
        partition_data = f.read()

    if len(partition_data) % PAGE_SIZE != 0:
        raise ValueError(
            f"Partition size {len(partition_data)} is not a multiple of page size {PAGE_SIZE}"
        )

    num_pages = len(partition_data) // PAGE_SIZE

    page_array = []
    for page_index in range(num_pages):
        page_base = PAGE_SIZE * page_index
        page_state = int.from_bytes(
            partition_data[page_base : page_base + 4], byteorder="little", signed=False
        )
        seq_no = int.from_bytes(
            partition_data[page_base + 4 : page_base + 8],
            byteorder="little",
            signed=False,
        )

        if (page_state & PSB_INIT) == 0:
            if (page_state & (PSB_FREE | PSB_CORRUPT)) == (PSB_FREE | PSB_CORRUPT):
                page_array.append((page_index, seq_no))

    page_array.sort(key=lambda x: x[1])

    ns_idx_to_name = {}
    nvs_table = {}
    blob_reassembly_table = {}

    def scan_page(page_data, page_index):
        entry_state_bitmap = page_data[ESB_OFFSET : (ESB_OFFSET + ESB_LENGTH)]

        entry_states = []
        for byte in entry_state_bitmap:
            for i in range(4):
                entry_state_bits = byte & 0x3
                if (entry_state_bits & ESB_WRITTEN) == 0:
                    if (entry_state_bits & ESB_ERASED) == 0:
                        entry_states.append(EntryState.ERASED)
                    else:
                        entry_states.append(EntryState.WRITTEN)
                else:
                    entry_states.append(EntryState.UNUSED)
                byte >>= 2

        del entry_states[126:128]

        i = 0
        while i < len(entry_states):
            if entry_states[i] == EntryState.WRITTEN:
                entry_base = ENTRY_0_OFFSET + (ENTRY_LENGTH * i)

                entry_ns = page_data[entry_base + NS_OFFSET]
                entry_type = page_data[entry_base + TYPE_OFFSET]
                entry_span = page_data[entry_base + SPAN_OFFSET]
                entry_chunk_idx = page_data[entry_base + CHUNK_IDX_OFFSET]
                entry_key_data = page_data[
                    entry_base + KEY_OFFSET : entry_base + KEY_OFFSET + KEY_LENGTH
                ]

                if 0 in entry_key_data:
                    entry_key_data = entry_key_data[0 : entry_key_data.find(0)]
                entry_key = entry_key_data.decode("ascii")

                do_not_add = False

                if entry_type < 0x20:
                    num_bytes = entry_type & 0xF
                    is_signed = False if (entry_type & 0x10) == 0 else True
                    entry_data = int.from_bytes(
                        page_data[
                            entry_base + DATA_OFFSET : entry_base
                            + DATA_OFFSET
                            + num_bytes
                        ],
                        byteorder="little",
                        signed=is_signed,
                    )

                elif EntryType(entry_type) == EntryType.STR:
                    data_size = int.from_bytes(
                        page_data[
                            entry_base + DATA_OFFSET : entry_base + DATA_OFFSET + 2
                        ],
                        byteorder="little",
                        signed=False,
                    )
                    entry_data = page_data[
                        entry_base + DATA_OFFSET + 8 : entry_base
                        + DATA_OFFSET
                        + 8
                        + data_size
                    ].decode("ascii")

                elif EntryType(entry_type) == EntryType.BLOB:
                    data_size = int.from_bytes(
                        page_data[
                            entry_base + DATA_OFFSET : entry_base + DATA_OFFSET + 2
                        ],
                        byteorder="little",
                        signed=False,
                    )
                    entry_data = page_data[
                        entry_base + DATA_OFFSET + 8 : entry_base
                        + DATA_OFFSET
                        + 8
                        + data_size
                    ]
                    namespace_name = ns_idx_to_name[entry_ns]
                    namespace_dict = blob_reassembly_table[namespace_name]
                    if entry_key not in namespace_dict:
                        namespace_dict[entry_key] = BlobReassembly()
                    namespace_dict[entry_key].add_chunk(entry_chunk_idx, entry_data)
                    do_not_add = True

                elif EntryType(entry_type) == EntryType.BLOB_IDX:
                    blob_size = int.from_bytes(
                        page_data[
                            entry_base + DATA_OFFSET : entry_base + DATA_OFFSET + 4
                        ],
                        byteorder="little",
                        signed=False,
                    )
                    chunk_count = int.from_bytes(
                        page_data[
                            entry_base + DATA_OFFSET + 4 : entry_base + DATA_OFFSET + 5
                        ],
                        byteorder="little",
                        signed=False,
                    )
                    chunk_start = int.from_bytes(
                        page_data[
                            entry_base + DATA_OFFSET + 5 : entry_base + DATA_OFFSET + 6
                        ],
                        byteorder="little",
                        signed=False,
                    )
                    namespace_name = ns_idx_to_name[entry_ns]
                    namespace_dict = blob_reassembly_table[namespace_name]
                    namespace_dict[entry_key].add_blob_index_info(
                        blob_size, chunk_count, chunk_start
                    )
                    entry_data = namespace_dict[entry_key].get_reassembled_blob()
                    entry_type = EntryType.BLOB.value

                else:
                    do_not_add = True

                if entry_ns == 0:
                    ns_idx_to_name[entry_data] = entry_key
                    nvs_table[entry_key] = {}
                    blob_reassembly_table[entry_key] = {}
                elif not do_not_add:
                    namespace_name = ns_idx_to_name[entry_ns]
                    namespace_dict = nvs_table[namespace_name]
                    namespace_dict[entry_key] = (entry_type, entry_data)

                if entry_span > 0:
                    i += entry_span
                else:
                    i += 1
            else:
                i += 1

    for page in page_array:
        page_idx = page[0]
        page_base = page_idx * PAGE_SIZE
        scan_page(partition_data[page_base : page_base + PAGE_SIZE], page_idx)

    result = {}
    nvs_data = nvs_table.get("chip-factory", {})
    for key, value in nvs_data.items():
        result[key] = value[1] if len(value) > 1 else value[0]
    return result
