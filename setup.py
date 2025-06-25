from setuptools import setup

PLUGIN_NAME = "uv"

microlib_name = f"flytekitplugins-{PLUGIN_NAME}"
plugin_requires = ["flytekit>=1.16,<2"]

__version__ = "0.0.0+develop"

setup(
    name=microlib_name,
    version=__version__,
    author="Francesco Rubbo",
    author_email="francescorubbo@users.noreply.github.com",
    description="A flytekit plugin for ImageSpec with a UV backend.",
    url="https://github.com/francescorubbo/flytekit-uv",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    namespace_packages=["flytekitplugins"],
    packages=[f"flytekitplugins.{PLUGIN_NAME}"],
    install_requires=plugin_requires,
    license="MIT",
    python_requires=">=3.12",
    classifiers=[
        "Intended Audience :: Science/Research",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Scientific/Engineering",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Software Development",
        "Topic :: Software Development :: Libraries",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    entry_points={"flytekit.plugins": [f"{PLUGIN_NAME}=flytekitplugins.{PLUGIN_NAME}"]},
)