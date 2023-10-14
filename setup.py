# Install package
import setuptools
import pathlib

doc = pathlib.Path(__file__).parent.joinpath('README.md').read_text(encoding="UTF-8")

setuptools.setup(
    name="cista",
    version="0.0.1",
    author="Vasanko lda",
    description="Dropbox-like file server with modern web interface",
    long_description=doc,
    long_description_content_type="text/markdown",
    url="",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
    ],
    install_requires=[
        "sanic",
        "msgspec",
        "watchdog",
        "pathvalidate",
    ],
)
