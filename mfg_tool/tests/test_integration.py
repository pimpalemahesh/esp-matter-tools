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

"""
Integration test suite for esp-matter-mfg-tool
"""

import click
import json
import os
import shutil
import shlex
import logging
from pathlib import Path
from typing import List, Optional, Tuple
from tests.utils import (
    run_command,
    parse_mfg_tool_output,
    Config,
    ParsedOutput,
    parse_command_arguments,
    parse_partition_bin,
)
from sources.cert_utils import (
    load_cert_from_file,
    extract_common_name,
    serialization,
)
from sources.utils import (
    ProductFinish,
    ProductColor,
    calendar_types_to_uint32,
    get_fixed_label_dict,
    get_supported_modes_dict,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestEspMatterMfgToolIntegration:
    """Integration test class for esp-matter-mfg-tool functionality"""

    @classmethod
    def setup_class(cls):
        """Set up test environment"""
        cls.test_data_dir = Path("test_data/")
        cls.output_dir = Path("out/")

        # Add test_data directory to PATH for chip-cert command
        os.environ["PATH"] = (
            f"{os.environ.get('PATH', '')}:{cls.test_data_dir.absolute()}"
        )

    def teardown_method(self):
        """Clean up after each test"""
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)

    def _validate_certificates_with_chip_cert(self, parsed_output: List[ParsedOutput]):
        """
        Validate certificates using chip-cert (skip if not available)

        Args:
            parsed_output: Parsed output of the esp-matter-mfg-tool command

        Returns:
            None
        """
        assert len(parsed_output) > 0, (
            "Could not find output path, Certificates not generated"
        )

        for output in parsed_output:
            dac_cert = Path(output.dac_cert)
            pai_cert = Path(output.pai_cert)
            paa_cert = Path(f"{self.test_data_dir}/Chip-Test-PAA-NoVID-Cert.pem")
            assert all([dac_cert.exists(), pai_cert.exists(), paa_cert.exists()]), (
                "Certificate files not generated"
            )

            # Run chip-cert validation
            cert_cmd = (
                f"chip-cert validate-att-cert -d {dac_cert} -i {pai_cert} -a {paa_cert}"
            )
            result = run_command(cert_cmd)
            assert result.returncode == 0, (
                f"Certificate validation failed: {result.stderr}"
            )
            logger.info("Certificate chain validated successfully")

    def _validate_no_bin_files(self, output: str):
        """
        Validate that no binary partition files are generated

        Args:
            output: Output of the esp-matter-mfg-tool command

        Returns:
            None
        """
        assert "*-partition.bin" not in output, (
            "partition.bin files generated but expected to be skipped"
        )
        logger.info("No partition.bin files generated")

    def _validate_secure_cert_partitions(
        self, parsed_output: List[ParsedOutput], should_exist: bool = True
    ):
        """
        Validate that secure cert partition files are generated when expected

        Args:
            parsed_output: Parsed output of the esp-matter-mfg-tool command
            should_exist: Whether secure cert partition files should exist

        Returns:
            None
        """
        for output in parsed_output:
            secure_cert_exists = Path(output.secure_cert_bin).exists()
            if should_exist:
                assert secure_cert_exists, (
                    f"Secure cert partition file not found: {output.secure_cert_bin}"
                )
                logger.info(
                    f"Secure cert partition file validated: {output.secure_cert_bin}"
                )
            else:
                assert not secure_cert_exists, (
                    f"Secure cert partition file should not exist: {output.secure_cert_bin}"
                )
                logger.info("No secure cert partition files found as expected")

    def _validate_output_paths_with_dac_cert_common_name(
        self, parsed_output: List[ParsedOutput], present: bool = True
    ):
        """
        Validate that output paths match DAC certificate common names

        Args:
            parsed_output: Parsed output of the esp-matter-mfg-tool command
            present: Whether the DAC certificate common name should be present in the output path

        Returns:
            None
        """
        for output in parsed_output:
            dac_cert = load_cert_from_file(output.dac_cert)
            cn = extract_common_name(dac_cert.subject)
            if present:
                assert cn in output.out_path, (
                    "DAC certificate common name not found in output path"
                )
            else:
                assert cn not in output.out_path, (
                    "DAC certificate common name found in output path"
                )
        logger.info("Output paths validated successfully")

    def _validate_command_output(self, output: str, config: Config):
        """
        Validate command output based on config flags

        Args:
            output: Output of the esp-matter-mfg-tool command
            config: Configuration for the test case

        Returns:
            None
        """
        assert config.expected_output in output, (
            f"Expected output not found: {config.expected_output}"
        )

        if config.validate_no_bin:
            self._validate_no_bin_files(output)

        parsed_output = parse_mfg_tool_output(output)

        if config.validate_csv_quoting:
            self._validate_csv_quoting(config.command)
        if config.validate_partition_bin:
            self._validate_partition_bin(config.command, parsed_output)

        if config.validate_cert:
            self._validate_certificates_with_chip_cert(parsed_output)
        if config.validate_cn_in_path or config.validate_cn_not_in_path:
            self._validate_output_paths_with_dac_cert_common_name(
                parsed_output, True if config.validate_cn_in_path else False
            )
        if config.validate_secure_cert:
            self._validate_secure_cert_partitions(parsed_output, should_exist=True)
        if config.validate_no_secure_cert_bin:
            self._validate_secure_cert_partitions(parsed_output, should_exist=False)

    def _load_test_data(self) -> List[Config]:
        """
        Load test configurations from JSON file

        Args:
            None

        Returns:
            List[Config]: List of test configurations
        """
        test_data_file = Path(f"{self.test_data_dir}/test_integration_inputs.json")
        with open(test_data_file, "r") as f:
            data = json.load(f)

        return [Config.from_dict(test) for test in data.get("tests", [])]

    def _extract_outdir(self, cmd: str) -> Optional[str]:
        """
        Get the outdir from the command if present
        """
        args = shlex.split(cmd)
        for i, arg in enumerate(args):
            if arg == "--outdir" and i + 1 < len(args):
                return args[i + 1]
            elif arg.startswith("--outdir="):
                return arg.split("=", 1)[1]
        return None

    def _extract_vid_pid(self, cmd: str) -> Optional[Tuple[str, str]]:
        """
        Get the vid and pid string from the command if present
        """
        args = shlex.split(cmd)
        vid, pid = None, None
        for i, arg in enumerate(args):
            if (arg == "-v" or arg == "--vendor-id") and i + 1 < len(args):
                vid = args[i + 1]
            elif (arg == "-p" or arg == "--product-id") and i + 1 < len(args):
                pid = args[i + 1]
        return vid, pid

    def _extract_vid_pid_str(self, cmd: str) -> str:
        vid, pid = self._extract_vid_pid(cmd)
        return f"{int(vid, 16):04x}_{int(pid, 16):04x}"

    def run_single_test(self, test_num: int, config: Config):
        """
        Run a single test case

        Args:
            test_num: Test number
            config: Configuration for the test case

        Returns:
            None
        """
        logger.info(f"\n\n--- Test {test_num} - {config.description} ---")
        logger.info(f"Command: {config.command}")
        logger.info(f"Expected output: {config.expected_output}")

        # use the outdir from the command if present, else fallback to default outdir
        outdir_in_cmd = self._extract_outdir(config.command)
        vid_pid_str = self._extract_vid_pid_str(config.command)
        self.output_dir = (
            Path(outdir_in_cmd) if outdir_in_cmd else Path(f"out/{vid_pid_str}")
        )

        # Run the command
        result = run_command(config.command)
        output = result.stdout + result.stderr

        # Validate output
        self._validate_command_output(output, config)

        logger.info(f"Test {test_num} passed successfully")

    def test_esp_matter_mfg_tool_parametrized(self):
        """Run all parameterized test cases for esp-matter-mfg-tool"""
        test_configs = self._load_test_data()

        for test_num, config in enumerate(test_configs, 1):
            self.run_single_test(test_num, config)
            self.teardown_method()

    def _validate_csv_quoting(self, command: str):
        import csv

        outdir_in_cmd = self._extract_outdir(command)
        vid_pid_str = self._extract_vid_pid_str(command)
        out_dir = Path(outdir_in_cmd) if outdir_in_cmd else Path(f"out/{vid_pid_str}")

        master_csv = Path(out_dir) / "staging" / "master.csv"
        assert master_csv.exists(), "master.csv not found"

        with open(master_csv, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                assert "Test Vendor,LLC" == row["vendor-name"], (
                    "Vendor name should be quoted"
                )

    def _validate_single_partition(self, cmd_args: dict, partition_data: dict):
        """
        Validate a single partition's data against command arguments

        Args:
            cmd_args: Parsed command arguments
            partition_data: partition data from partition
        """
        vendor_id_expected = cmd_args.get("vendor-id")
        vendor_id_actual = partition_data.get("vendor-id")
        if vendor_id_expected is not None and vendor_id_actual is not None:
            assert vendor_id_actual == vendor_id_expected, (
                f"Vendor ID mismatch: expected {vendor_id_expected} got {vendor_id_actual}"
            )
            logger.info(f"✓ Vendor ID validated: {vendor_id_actual}")

        product_id_expected = cmd_args.get("product-id")
        product_id_actual = partition_data.get("product-id")
        if product_id_expected is not None and product_id_actual is not None:
            assert product_id_actual == product_id_expected, (
                f"Product ID mismatch: expected {product_id_expected} got {product_id_actual}"
            )
            logger.info(f"✓ Product ID validated: {product_id_actual}")

        vendor_name_expected = cmd_args.get("vendor-name")
        vendor_name_actual = partition_data.get("vendor-name")
        if vendor_name_expected is not None and vendor_name_actual is not None:
            vendor_name_actual_clean = vendor_name_actual.rstrip("\x00").strip()
            vendor_name_expected_clean = vendor_name_expected.strip()
            assert vendor_name_actual_clean == vendor_name_expected_clean, (
                f"Vendor name mismatch: expected '{vendor_name_expected_clean}' got '{vendor_name_actual_clean}'"
            )
            logger.info(f"✓ Vendor name validated: {vendor_name_actual_clean}")

        product_name_expected = cmd_args.get("product-name")
        product_name_actual = partition_data.get("product-name")
        if product_name_expected is not None and product_name_actual is not None:
            product_name_actual_clean = product_name_actual.rstrip("\x00").strip()
            product_name_expected_clean = product_name_expected.strip()
            assert product_name_actual_clean == product_name_expected_clean, (
                f"Product name mismatch: expected '{product_name_expected_clean}' got '{product_name_actual_clean}'"
            )
            logger.info(f"✓ Product name validated: {product_name_actual_clean}")

        hw_ver_expected = cmd_args.get("hw-ver")
        hw_ver_actual = partition_data.get("hardware-ver")
        if hw_ver_expected is not None and hw_ver_actual is not None:
            assert hw_ver_actual == hw_ver_expected, (
                f"Hardware version mismatch: expected {hw_ver_expected} got {hw_ver_actual}"
            )
            logger.info(f"✓ Hardware version validated: {hw_ver_actual}")

        hw_ver_str_expected = cmd_args.get("hw-ver-str")
        hw_ver_str_actual = partition_data.get("hw-ver-str")
        if hw_ver_str_expected is not None and hw_ver_str_actual is not None:
            hw_ver_str_actual_clean = hw_ver_str_actual.rstrip("\x00").strip()
            hw_ver_str_expected_clean = hw_ver_str_expected.strip()
            assert hw_ver_str_actual_clean == hw_ver_str_expected_clean, (
                f"Hardware version string mismatch: expected '{hw_ver_str_expected_clean}' got '{hw_ver_str_actual_clean}'"
            )
            logger.info(
                f"✓ Hardware version string validated: {hw_ver_str_actual_clean}"
            )

        serial_num_expected = cmd_args.get("serial-num")
        serial_num_actual = partition_data.get("serial-num")
        if serial_num_expected is not None and serial_num_actual is not None:
            serial_num_actual_clean = serial_num_actual.rstrip("\x00").strip()
            serial_num_expected_clean = serial_num_expected.strip()
            assert serial_num_actual_clean == serial_num_expected_clean, (
                f"Serial number mismatch: expected '{serial_num_expected_clean}' got '{serial_num_actual_clean}'"
            )
            logger.info(f"✓ Serial number validated: {serial_num_actual_clean}")

        mfg_date_expected = cmd_args.get("mfg-date")
        mfg_date_actual = partition_data.get("mfg-date")
        if mfg_date_expected is not None and mfg_date_actual is not None:
            mfg_date_actual_clean = mfg_date_actual.rstrip("\x00").strip()
            assert str(mfg_date_actual_clean) == str(mfg_date_expected), (
                f"Manufacturing date mismatch: expected {mfg_date_expected} got {mfg_date_actual}"
            )
            logger.info(f"✓ Manufacturing date validated: {mfg_date_actual}")

        product_label_expected = cmd_args.get("product-label")
        product_label_actual = partition_data.get("product-label")
        if product_label_expected is not None and product_label_actual is not None:
            product_label_actual_clean = product_label_actual.rstrip("\x00").strip()
            product_label_expected_clean = product_label_expected.strip()
            assert product_label_actual_clean == product_label_expected_clean, (
                f"Product label mismatch: expected '{product_label_expected_clean}' got '{product_label_actual_clean}'"
            )
            logger.info(f"✓ Product label validated: {product_label_actual_clean}")

        product_url_expected = cmd_args.get("product-url")
        product_url_actual = partition_data.get("product-url")
        if product_url_expected is not None and product_url_actual is not None:
            product_url_actual_clean = product_url_actual.rstrip("\x00").strip()
            product_url_expected_clean = product_url_expected.strip()
            assert product_url_actual_clean == product_url_expected_clean, (
                f"Product URL mismatch: expected '{product_url_expected_clean}' got '{product_url_actual_clean}'"
            )
            logger.info(f"✓ Product URL validated: {product_url_actual_clean}")

        part_number_expected = cmd_args.get("part-number")
        part_number_actual = partition_data.get("part-number")
        if part_number_expected is not None and part_number_actual is not None:
            part_number_actual_clean = part_number_actual.rstrip("\x00").strip()
            part_number_expected_clean = part_number_expected.strip()
            assert part_number_actual_clean == part_number_expected_clean, (
                f"Part number mismatch: expected '{part_number_expected_clean}' got '{part_number_actual_clean}'"
            )
            logger.info(f"✓ Part number validated: {part_number_actual_clean}")

        product_finish_expected = cmd_args.get("product-finish")
        product_finish_actual = partition_data.get("product-finish")
        if product_finish_expected is not None and product_finish_actual is not None:
            product_finish_expected_enum = ProductFinish[product_finish_expected].value
            assert product_finish_actual == product_finish_expected_enum, (
                f"Product finish mismatch: expected '{product_finish_expected}' got '{product_finish_actual}'"
            )
            logger.info(
                f"✓ Product finish present in partition: {product_finish_expected}"
            )

        product_color_expected = cmd_args.get("product-color")
        product_color_actual = partition_data.get("product-color")
        if product_color_expected is not None and product_color_actual is not None:
            product_color_expected_enum = ProductColor[product_color_expected].value
            assert product_color_actual == product_color_expected_enum, (
                f"Product color mismatch: expected '{product_color_expected}' got '{product_color_actual}'"
            )
            logger.info(
                f"✓ Product color present in partition: {product_color_expected}"
            )

        calendar_types_expected = cmd_args.get("calendar-types")
        calendar_types_actual = partition_data.get("cal-types")
        if calendar_types_expected is not None and calendar_types_actual is not None:
            # Supported Calendar types is stored as a bit array in one uint32_t.
            calendar_types_expected_clean = calendar_types_to_uint32(
                calendar_types_expected
            )
            assert calendar_types_actual == calendar_types_expected_clean, (
                f"Calendar types mismatch: expected '{calendar_types_expected_clean}' got '{calendar_types_actual}'"
            )
            logger.info(f"✓ Calendar types validated: {calendar_types_expected}")

        passcode_expected = cmd_args.get("passcode")
        passcode_actual = partition_data.get("passcode")
        if passcode_expected is not None and passcode_actual is not None:
            assert passcode_actual == passcode_expected, (
                f"Passcode mismatch: expected {passcode_expected} got {passcode_actual}"
            )
            logger.info(f"✓ Passcode validated: {passcode_actual}")

        discriminator_expected = cmd_args.get("discriminator")
        discriminator_actual = partition_data.get("discriminator")
        if discriminator_expected is not None:
            assert discriminator_actual == discriminator_expected, (
                f"Discriminator mismatch: expected {discriminator_expected} got {discriminator_actual}"
            )
            logger.info(f"✓ Discriminator validated: {discriminator_actual}")

        iteration_count_expected = cmd_args.get("iteration-count")
        iteration_count_actual = partition_data.get("iteration-count")
        if iteration_count_expected is not None:
            assert iteration_count_actual == iteration_count_expected, (
                f"Iteration count mismatch: expected {iteration_count_expected} got {iteration_count_actual}"
            )
            logger.info(f"✓ Iteration count validated: {iteration_count_actual}")

        salt_expected = cmd_args.get("salt")
        salt_actual = partition_data.get("salt")
        if salt_expected is not None and salt_actual is not None:
            salt_actual_clean = salt_actual.rstrip("\x00").strip()
            salt_expected_clean = salt_expected.strip()
            assert salt_actual_clean == salt_expected_clean, (
                f"Salt mismatch: expected '{salt_expected_clean}' got '{salt_actual_clean}'"
            )
            logger.info(f"✓ Salt validated {salt_actual_clean}")

        verifier_expected = cmd_args.get("verifier")
        verifier_actual = partition_data.get("verifier")
        if verifier_expected is not None and verifier_actual is not None:
            verifier_actual_clean = verifier_actual.rstrip("\x00").strip()
            verifier_expected_clean = verifier_expected.strip()
            assert verifier_actual_clean == verifier_expected_clean, (
                f"Verifier mismatch: expected '{verifier_expected_clean}' got '{verifier_actual_clean}'"
            )
            logger.info(f"✓ Verifier validated {verifier_actual_clean}")

        if not cmd_args.get("dac-in-secure-cert"):
            if cmd_args.get("dac-cert") is not None:
                dac_cert_actual = partition_data.get("dac-cert")
                assert dac_cert_actual is not None, (
                    "DAC certificate not found in partition"
                )
                assert dac_cert_actual == cmd_args.get("dac-cert"), (
                    "DAC certificate mismatch"
                )
                logger.info("✓ DAC certificate validated")

            if cmd_args.get("dac-key") is not None:
                dac_key_actual = partition_data.get("dac-key")
                assert dac_key_actual is not None, "DAC key not found in partition"
                assert dac_key_actual == cmd_args.get("dac-key"), "DAC key mismatch"
                logger.info("✓ DAC key validated")

            if cmd_args.get("dac-pub-key") is not None:
                dac_pub_key_actual = partition_data.get("dac-pub-key")
                assert dac_pub_key_actual is not None, (
                    "DAC public key not found in partition"
                )
                assert dac_pub_key_actual == cmd_args.get("dac-pub-key"), (
                    "DAC public key mismatch"
                )
                logger.info("✓ DAC public key validated")

            if cmd_args.get("pai-cert") is not None:
                pai_cert_actual = partition_data.get("pai-cert")
                assert pai_cert_actual is not None, (
                    "PAI certificate not found in partition"
                )
                assert pai_cert_actual == cmd_args.get("pai-cert"), (
                    "PAI certificate mismatch"
                )
                logger.info("✓ PAI certificate validated")
                pai_cert_actual = partition_data.get("pai-cert")

        # Validate certificate declaration
        if cmd_args.get("cert-dclrn"):
            cert_dclrn_actual = partition_data.get("cert-dclrn")
            if cert_dclrn_actual is not None:
                logger.info(
                    f"✓ Certificate declaration present in partition (size: {len(cert_dclrn_actual)} bytes)"
                )

        if cmd_args.get("enable-dynamic-passcode"):
            verifier_entry = partition_data.get("verifier")
            assert verifier_entry is None, (
                "Verifier should not be present when enable-dynamic-passcode is set"
            )
            logger.info("✓ Verifier correctly absent (dynamic passcode enabled)")

        rd_id_uid_expected = cmd_args.get("rd-id-uid")
        rd_id_uid_actual = partition_data.get("rd-id-uid")
        if rd_id_uid_expected is not None and rd_id_uid_actual is not None:
            rd_id_uid_actual_hex = rd_id_uid_actual.hex()
            assert rd_id_uid_actual_hex == rd_id_uid_expected, (
                f"Rotating device ID UID mismatch: expected '{rd_id_uid_expected}' got '{rd_id_uid_actual_hex}'"
            )
            logger.info(f"✓ Rotating device ID UID validated {rd_id_uid_actual_hex}")

        if cmd_args.get("enable-rotating-device-id"):
            rd_id_uid_actual = partition_data.get("rd-id-uid")
            assert rd_id_uid_actual is not None, (
                "Rotating device ID not found in partition"
            )
            logger.info(
                "✓ Rotating device ID present in partition with enable-rotating-device-id flag set"
            )

        # Validate locales
        locales_expected = cmd_args.get("locales")
        if locales_expected is not None:
            locale_sz_actual = partition_data.get("locale-sz")
            if locale_sz_actual is not None:
                assert locale_sz_actual == len(locales_expected), (
                    f"Locale size mismatch: expected {len(locales_expected)}, got {locale_sz_actual}"
                )
                logger.info(f"✓ Locale size validated: {locale_sz_actual} bytes")

                for i, locale_expected in enumerate(locales_expected):
                    locale_key = f"locale/{i:x}"
                    locale_actual = partition_data.get(locale_key)
                    if locale_actual is not None:
                        locale_actual_clean = locale_actual.rstrip("\x00").strip()
                        locale_expected_clean = locale_expected.strip()
                        assert locale_actual_clean == locale_expected_clean, (
                            f"Locale {i} mismatch: expected '{locale_expected_clean}', got '{locale_actual_clean}'"
                        )
                        logger.info(f"✓ Locale {i} validated: {locale_actual_clean}")

        # Validate fixed-labels
        fixed_labels_expected = cmd_args.get("fixed-labels")
        if fixed_labels_expected is not None:
            fixed_labels_dict = get_fixed_label_dict(fixed_labels_expected)

            for endpoint, labels in fixed_labels_dict.items():
                fl_sz_key = f"fl-sz/{int(endpoint):x}"
                fl_sz_actual = partition_data.get(fl_sz_key)
                if fl_sz_actual is not None:
                    assert fl_sz_actual == len(labels), (
                        f"Fixed label size for endpoint {endpoint} mismatch: expected {len(labels)}, got {fl_sz_actual}"
                    )
                    logger.info(
                        f"✓ Fixed label size for endpoint {endpoint} validated: {fl_sz_actual}"
                    )

                    for i, label_dict in enumerate(labels):
                        fl_k_key = f"fl-k/{int(endpoint):x}/{i:x}"
                        fl_v_key = f"fl-v/{int(endpoint):x}/{i:x}"

                        fl_k_actual = partition_data.get(fl_k_key)
                        fl_v_actual = partition_data.get(fl_v_key)

                        label_key = list(label_dict.keys())[0]
                        label_value = list(label_dict.values())[0]

                        if fl_k_actual is not None:
                            fl_k_actual_clean = fl_k_actual.rstrip("\x00").strip()
                            assert fl_k_actual_clean == label_key, (
                                f"Fixed label key {endpoint}/{i} mismatch: expected '{label_key}', got '{fl_k_actual_clean}'"
                            )
                            logger.info(
                                f"✓ Fixed label key {endpoint}/{i} validated: {fl_k_actual_clean}"
                            )

                        if fl_v_actual is not None:
                            fl_v_actual_clean = fl_v_actual.rstrip("\x00").strip()
                            assert fl_v_actual_clean == label_value, (
                                f"Fixed label value {endpoint}/{i} mismatch: expected '{label_value}', got '{fl_v_actual_clean}'"
                            )
                            logger.info(
                                f"✓ Fixed label value {endpoint}/{i} validated: {fl_v_actual_clean}"
                            )

        # Validate supported-modes
        supported_modes_expected = cmd_args.get("supported-modes")
        if supported_modes_expected is not None:
            supported_modes_dict = get_supported_modes_dict(supported_modes_expected)

            for endpoint, modes in supported_modes_dict.items():
                sm_sz_key = f"sm-sz/{int(endpoint):x}"
                sm_sz_actual = partition_data.get(sm_sz_key)
                if sm_sz_actual is not None:
                    assert sm_sz_actual == len(modes), (
                        f"Supported mode size for endpoint {endpoint} mismatch: expected {len(modes)}, got {sm_sz_actual}"
                    )
                    logger.info(
                        f"✓ Supported mode size for endpoint {endpoint} validated: {sm_sz_actual}"
                    )

                    for i, mode_data in enumerate(modes):
                        sm_label_key = f"sm-label/{int(endpoint):x}/{i:x}"
                        sm_mode_key = f"sm-mode/{int(endpoint):x}/{i:x}"

                        sm_label_actual = partition_data.get(sm_label_key)
                        sm_mode_actual = partition_data.get(sm_mode_key)

                        if sm_label_actual is not None:
                            sm_label_actual_clean = sm_label_actual.rstrip(
                                "\x00"
                            ).strip()
                            assert sm_label_actual_clean == mode_data["Label"], (
                                f"Supported mode label {endpoint}/{i} mismatch: expected '{mode_data['Label']}', got '{sm_label_actual_clean}'"
                            )
                            logger.info(
                                f"✓ Supported mode label {endpoint}/{i} validated: {sm_label_actual_clean}"
                            )

                        if sm_mode_actual is not None:
                            assert sm_mode_actual == mode_data["Mode"], (
                                f"Supported mode value {endpoint}/{i} mismatch: expected {mode_data['Mode']}, got {sm_mode_actual}"
                            )
                            logger.info(
                                f"✓ Supported mode value {endpoint}/{i} validated: {sm_mode_actual}"
                            )

                        # Validate semantic tags if present
                        if mode_data["Semantic_Tag"]:
                            sm_st_sz_key = f"sm-st-sz/{int(endpoint):x}/{i:x}"
                            sm_st_sz_actual = partition_data.get(sm_st_sz_key)

                            if sm_st_sz_actual is not None:
                                assert sm_st_sz_actual == len(
                                    mode_data["Semantic_Tag"]
                                ), (
                                    f"Semantic tag size {endpoint}/{i} mismatch: expected {len(mode_data['Semantic_Tag'])}, got {sm_st_sz_actual}"
                                )
                                logger.info(
                                    f"✓ Semantic tag size {endpoint}/{i} validated: {sm_st_sz_actual}"
                                )

                                for j, tag in enumerate(mode_data["Semantic_Tag"]):
                                    st_v_key = f"st-v/{int(endpoint):x}/{i:x}/{j:x}"
                                    st_mfg_key = f"st-mfg/{int(endpoint):x}/{i:x}/{j:x}"

                                    st_v_actual = partition_data.get(st_v_key)
                                    st_mfg_actual = partition_data.get(st_mfg_key)

                                    if st_v_actual is not None:
                                        assert st_v_actual == tag["value"], (
                                            f"Semantic tag value {endpoint}/{i}/{j} mismatch: expected {tag['value']}, got {st_v_actual}"
                                        )
                                        logger.info(
                                            f"✓ Semantic tag value {endpoint}/{i}/{j} validated: {st_v_actual}"
                                        )

                                    if st_mfg_actual is not None:
                                        assert st_mfg_actual == tag["mfgCode"], (
                                            f"Semantic tag mfgCode {endpoint}/{i}/{j} mismatch: expected {tag['mfgCode']}, got {st_mfg_actual}"
                                        )
                                        logger.info(
                                            f"✓ Semantic tag mfgCode {endpoint}/{i}/{j} validated: {st_mfg_actual}"
                                        )

        logger.info("✓ All partition validations passed!")

    def _validate_partition_bin(self, command: str, parsed_output: List[ParsedOutput]):
        """
        Validate the generated partition.bin file data matches the input arguments

        Args:
            command: The command used to generate the partition
            parsed_output: Parsed output of the esp-matter-mfg-tool command
        """
        cmd_args = parse_command_arguments(command)

        for output in parsed_output:
            partition_bin_path = Path(output.partition_bin)
            dac_cert_path = Path(output.dac_cert)
            dac_cert_data = (
                dac_cert_path.read_bytes() if dac_cert_path.exists() else None
            )
            dac_key_path = Path(output.dac_key)
            dac_key_bytes = dac_key_path.read_bytes() if dac_key_path.exists() else None
            dac_key_data = None
            if dac_key_bytes is not None:
                try:
                    private_key = serialization.load_der_private_key(
                        dac_key_bytes, password=None
                    )
                    dac_key_data = private_key.private_numbers().private_value.to_bytes(
                        32, "big"
                    )
                except Exception as e:
                    logger.error(f"Failed to load DER key: {e}")
                    raise
            dac_pub_key_path = Path(output.dac_pub_key)
            dac_pub_key_bytes = (
                dac_pub_key_path.read_bytes() if dac_pub_key_path.exists() else None
            )
            dac_pub_key_data = None
            if dac_pub_key_bytes is not None:
                dac_pub_key_data = dac_pub_key_bytes
            pai_cert_path = Path(output.pai_cert)
            pai_cert_data = (
                pai_cert_path.read_bytes() if pai_cert_path.exists() else None
            )
            cmd_args.update(
                {
                    "dac-cert": (dac_cert_data),
                    "dac-key": (dac_key_data),
                    "dac-pub-key": (dac_pub_key_data),
                    "pai-cert": (pai_cert_data),
                }
            )
            if not partition_bin_path.exists():
                logger.warning(f"Partition file not found: {partition_bin_path}")
                continue

            try:
                partition_data = parse_partition_bin(str(partition_bin_path))
            except Exception as e:
                logger.error(f"Failed to parse partition binary: {e}")
                raise

            self._validate_single_partition(cmd_args, partition_data)


@click.command()
@click.option("--test-num", type=int, default=1, help="Test number")
@click.option(
    "--description", type=str, default="", help="Description of the test case"
)
@click.option(
    "--expected-output",
    type=str,
    default="Generated output files at:",
    help="Expected output of the test case",
)
@click.option("--command", type=str, required=True, help="Command to run")
@click.option(
    "--validate-partition-bin",
    is_flag=True,
    default=False,
    help="Validate partition bin",
)
@click.option(
    "--validate-cert", is_flag=True, default=False, help="Validate certificates"
)
@click.option(
    "--validate-cn-in-path", is_flag=True, default=False, help="Validate CN in path"
)
@click.option(
    "--validate-cn-not-in-path",
    is_flag=True,
    default=False,
    help="Validate CN not in path",
)
@click.option("--validate-no-bin", is_flag=True, default=False, help="Validate no bin")
@click.option(
    "--validate-csv-quoting", is_flag=True, default=False, help="Validate CSV quoting"
)
@click.option(
    "--validate-secure-cert", is_flag=True, default=False, help="Validate secure cert"
)
@click.option(
    "--validate-no-secure-cert-bin",
    is_flag=True,
    default=False,
    help="Validate no secure cert bin",
)
def main(
    test_num,
    description,
    expected_output,
    command,
    validate_partition_bin,
    validate_cert,
    validate_cn_in_path,
    validate_cn_not_in_path,
    validate_no_bin,
    validate_csv_quoting,
    validate_secure_cert,
    validate_no_secure_cert_bin,
):
    logger.info(f"Running command: {command}")
    config = Config(
        description=description,
        expected_output=expected_output,
        command=command,
        validate_partition_bin=validate_partition_bin,
        validate_cert=validate_cert,
        validate_cn_in_path=validate_cn_in_path,
        validate_cn_not_in_path=validate_cn_not_in_path,
    )
    test_suite = TestEspMatterMfgToolIntegration()
    test_suite.run_single_test(1, config)


if __name__ == "__main__":
    main()
