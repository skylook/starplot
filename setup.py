from setuptools import setup, find_packages

setup(
    name="starplot",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "numpy",
        "rtree",
        "shapely",
        "pytz",
        "holoviews>=1.15.0",  # Add HoloViews as a required dependency
        "matplotlib>=3.4.0",   # Keep matplotlib as it's still used by default
        "ibis-framework",      # Required for constellation models
    ],
    extras_require={
        "bokeh": ["bokeh>=2.4.0"],     # Optional Bokeh backend
        "plotly": ["plotly>=5.3.0"],   # Optional Plotly backend
    },
    python_requires=">=3.8",
    author="Your Name",
    author_email="your.email@example.com",
    description="A Python library for plotting astronomical charts",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/starplot",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Scientific/Engineering :: Astronomy",
    ],
) 