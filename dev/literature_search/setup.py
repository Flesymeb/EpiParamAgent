"""Setup script for Research Pilot."""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text() if readme_file.exists() else ""

setup(
    name="research-pilot",
    version="0.1.0",
    author="Anik Tahabilder",
    author_email="your-email@example.com",
    description="AI-powered research assistant for academic workflows",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/research-pilot",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.10",
    install_requires=[
        "torch>=2.0.0",
        "sentence-transformers>=2.2.2",
        "transformers>=4.30.0",
        "langchain>=0.1.0",
        "langgraph>=0.0.20",
        "PyMuPDF>=1.23.0",
        "qdrant-client>=1.7.0",
        "streamlit>=1.29.0",
        "requests>=2.31.0",
        "pandas>=2.1.0",
        "numpy>=1.24.0",
        "pydantic>=2.5.0",
        "python-dotenv>=1.0.0",
        "tqdm>=4.66.0",
        "tenacity>=8.2.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "black>=23.11.0",
            "ruff>=0.1.6",
            "mypy>=1.7.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "research-pilot=research_pilot.cli:main",
        ],
    },
)
