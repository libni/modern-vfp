#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name="modern-vfp",
    version="1.5.0",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "foxnext = modern_vfp.repl:main",
            "modern-vfp = modern_vfp.repl:main",
        ],
    },
)
