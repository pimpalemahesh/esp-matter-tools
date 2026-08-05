#!/usr/bin/env python3

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

import os
import sys


def get_install_requires():
    with open(os.path.join(os.path.dirname(__file__), "requirements.txt")) as f:
        return f.read().splitlines()


try:
    from setuptools import find_packages, setup
except ImportError:
    print("Package setuptools is missing from your Python installation.")
    exit(1)

VERSION = "0.1.0"

long_description = """
esp-matter-datamodel
====================

A tool-neutral, versioned representation of the Matter data model as JSON,
derived from the connectedhomeip specification XML files. It defines the shared
JSON schema, the spec-XML parser, and a validating loader used across
esp-matter-tools.

Source: https://github.com/espressif/esp-matter-tools/tree/main/esp-matter-datamodel
"""

setup(
    name="esp-matter-datamodel",
    version=VERSION,
    description="Tool-neutral Matter data model as versioned JSON (schema + parser + loader).",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/espressif/esp-matter-tools/tree/main/esp-matter-datamodel",
    author="Espressif Systems",
    author_email="",
    license="Apache-2.0",
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "Operating System :: POSIX",
        "Operating System :: MacOS :: MacOS X",
        "Topic :: Software Development :: Embedded Systems",
    ],
    python_requires=">=3.10",
    setup_requires=(["wheel"] if "bdist_wheel" in sys.argv else []),
    install_requires=get_install_requires(),
    include_package_data=True,
    packages=find_packages(exclude=["tests", "tests.*"]),
    package_data={
        "esp_matter_datamodel": ["schema/*.json", "datamodels/*.json"],
    },
    entry_points={
        "console_scripts": [
            "esp-matter-datamodel=esp_matter_datamodel.cli.main:main",
        ],
    },
)
