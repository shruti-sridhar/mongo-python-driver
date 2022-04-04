import os
import platform
import re
import sys
import warnings

if sys.version_info[:3] < (3, 6, 2):
    raise RuntimeError("Python version >= 3.6.2 required.")


# Hack to silence atexit traceback in some Python versions
try:
    import multiprocessing  # noqa: F401
except ImportError:
    pass

from setuptools import setup

if sys.version_info[:2] < (3, 10):
    from distutils.cmd import Command
    from distutils.command.build_ext import build_ext
    from distutils.core import Extension
else:
    from setuptools import Command
    from setuptools.command.build_ext import build_ext
    from setuptools.extension import Extension

_HAVE_SPHINX = True
try:
    from sphinx.cmd import build as sphinx
except ImportError:
    try:
        import sphinx
    except ImportError:
        _HAVE_SPHINX = False

version = "4.1.0"

f = open("README.rst")
try:
    try:
        readme_content = f.read()
    except BaseException:
        readme_content = ""
finally:
    f.close()

# PYTHON-654 - Clang doesn't support -mno-fused-madd but the pythons Apple
# ships are built with it. This is a problem starting with Xcode 5.1
# since clang 3.4 errors out when it encounters unrecognized compiler
# flags. This hack removes -mno-fused-madd from the CFLAGS automatically
# generated by distutils for Apple provided pythons, allowing C extension
# builds to complete without error. The inspiration comes from older
# versions of distutils.sysconfig.get_config_vars.
if sys.platform == "darwin" and "clang" in platform.python_compiler().lower():
    from distutils.sysconfig import get_config_vars

    res = get_config_vars()
    for key in ("CFLAGS", "PY_CFLAGS"):
        if key in res:
            flags = res[key]
            flags = re.sub("-mno-fused-madd", "", flags)
            res[key] = flags


class test(Command):
    description = "run the tests"

    user_options = [
        ("test-module=", "m", "Discover tests in specified module"),
        ("test-suite=", "s", "Test suite to run (e.g. 'some_module.test_suite')"),
        ("failfast", "f", "Stop running tests on first failure or error"),
        ("xunit-output=", "x", "Generate a results directory with XUnit XML format"),
    ]

    def initialize_options(self):
        self.test_module = None
        self.test_suite = None
        self.failfast = False
        self.xunit_output = None

    def finalize_options(self):
        if self.test_suite is None and self.test_module is None:
            self.test_module = "test"
        elif self.test_module is not None and self.test_suite is not None:
            raise Exception("You may specify a module or suite, but not both")

    def run(self):
        # Installing required packages, running egg_info and build_ext are
        # part of normal operation for setuptools.command.test.test
        if self.distribution.install_requires:
            self.distribution.fetch_build_eggs(self.distribution.install_requires)
        if self.distribution.tests_require:
            self.distribution.fetch_build_eggs(self.distribution.tests_require)
        if self.xunit_output:
            self.distribution.fetch_build_eggs(["unittest-xml-reporting"])
        self.run_command("egg_info")
        build_ext_cmd = self.reinitialize_command("build_ext")
        build_ext_cmd.inplace = 1
        self.run_command("build_ext")

        # Construct a TextTestRunner directly from the unittest imported from
        # test, which creates a TestResult that supports the 'addSkip' method.
        # setuptools will by default create a TextTestRunner that uses the old
        # TestResult class.
        from test import PymongoTestRunner, test_cases, unittest

        if self.test_suite is None:
            all_tests = unittest.defaultTestLoader.discover(self.test_module)
            suite = unittest.TestSuite()
            suite.addTests(sorted(test_cases(all_tests), key=lambda x: x.__module__))
        else:
            suite = unittest.defaultTestLoader.loadTestsFromName(self.test_suite)
        if self.xunit_output:
            from test import PymongoXMLTestRunner

            runner = PymongoXMLTestRunner(
                verbosity=2, failfast=self.failfast, output=self.xunit_output
            )
        else:
            runner = PymongoTestRunner(verbosity=2, failfast=self.failfast)
        result = runner.run(suite)
        sys.exit(not result.wasSuccessful())


class doc(Command):

    description = "generate or test documentation"

    user_options = [("test", "t", "run doctests instead of generating documentation")]

    boolean_options = ["test"]

    def initialize_options(self):
        self.test = False

    def finalize_options(self):
        pass

    def run(self):

        if not _HAVE_SPHINX:
            raise RuntimeError("You must install Sphinx to build or test the documentation.")

        if self.test:
            path = os.path.join(os.path.abspath("."), "doc", "_build", "doctest")
            mode = "doctest"
        else:
            path = os.path.join(os.path.abspath("."), "doc", "_build", version)
            mode = "html"

            try:
                os.makedirs(path)
            except BaseException:
                pass

        sphinx_args = ["-E", "-b", mode, "doc", path]

        # sphinx.main calls sys.exit when sphinx.build_main exists.
        # Call build_main directly so we can check status and print
        # the full path to the built docs.
        if hasattr(sphinx, "build_main"):
            status = sphinx.build_main(sphinx_args)
        else:
            status = sphinx.main(sphinx_args)

        if status:
            raise RuntimeError("documentation step '%s' failed" % (mode,))

        sys.stdout.write(
            "\nDocumentation step '%s' performed, results here:\n   %s/\n" % (mode, path)
        )


class custom_build_ext(build_ext):
    """Allow C extension building to fail.

    The C extension speeds up BSON encoding, but is not essential.
    """

    warning_message = """
********************************************************************
WARNING: %s could not
be compiled. No C extensions are essential for PyMongo to run,
although they do result in significant speed improvements.
%s

Please see the installation docs for solutions to build issues:

https://pymongo.readthedocs.io/en/stable/installation.html

Here are some hints for popular operating systems:

If you are seeing this message on Linux you probably need to
install GCC and/or the Python development package for your
version of Python.

Debian and Ubuntu users should issue the following command:

    $ sudo apt-get install build-essential python-dev

Users of Red Hat based distributions (RHEL, CentOS, Amazon Linux,
Oracle Linux, Fedora, etc.) should issue the following command:

    $ sudo yum install gcc python-devel

If you are seeing this message on Microsoft Windows please install
PyMongo using pip. Modern versions of pip will install PyMongo
from binary wheels available on pypi. If you must install from
source read the documentation here:

https://pymongo.readthedocs.io/en/stable/installation.html#installing-from-source-on-windows

If you are seeing this message on macOS / OSX please install PyMongo
using pip. Modern versions of pip will install PyMongo from binary
wheels available on pypi. If wheels are not available for your version
of macOS / OSX, or you must install from source read the documentation
here:

https://pymongo.readthedocs.io/en/stable/installation.html#osx
********************************************************************
"""

    def run(self):
        try:
            build_ext.run(self)
        except Exception:
            e = sys.exc_info()[1]
            sys.stdout.write("%s\n" % str(e))
            warnings.warn(
                self.warning_message
                % (
                    "Extension modules",
                    "There was an issue with your platform configuration - see above.",
                )
            )

    def build_extension(self, ext):
        name = ext.name
        try:
            build_ext.build_extension(self, ext)
        except Exception:
            e = sys.exc_info()[1]
            sys.stdout.write("%s\n" % str(e))
            warnings.warn(
                self.warning_message
                % (
                    "The %s extension module" % (name,),
                    "The output above this warning shows how the compilation failed.",
                )
            )


ext_modules = [
    Extension(
        "bson._cbson",
        include_dirs=["bson"],
        sources=[
            "bson/_cbsonmodule.c",
            "bson/time64.c",
            "bson/buffer.c",
            "bson/encoding_helpers.c",
        ],
    ),
    Extension(
        "pymongo._cmessage",
        include_dirs=["bson"],
        sources=["pymongo/_cmessagemodule.c", "bson/buffer.c"],
    ),
]

# PyOpenSSL 17.0.0 introduced support for OCSP. 17.1.0 introduced
# a related feature we need. 17.2.0 fixes a bug
# in set_default_verify_paths we should really avoid.
# service_identity 18.1.0 introduced support for IP addr matching.
pyopenssl_reqs = ["pyopenssl>=17.2.0", "requests<3.0.0", "service_identity>=18.1.0"]
if sys.platform in ("win32", "darwin"):
    # Fallback to certifi on Windows if we can't load CA certs from the system
    # store and just use certifi on macOS.
    # https://www.pyopenssl.org/en/stable/api/ssl.html#OpenSSL.SSL.Context.set_default_verify_paths
    pyopenssl_reqs.append("certifi")

extras_require = {
    "encryption": ["pymongocrypt>=1.2.0,<2.0.0"],
    "ocsp": pyopenssl_reqs,
    "snappy": ["python-snappy"],
    "zstd": ["zstandard"],
    "aws": ["pymongo-auth-aws<2.0.0"],
    "srv": ["dnspython>=1.16.0,<3.0.0"],
}

# GSSAPI extras
if sys.platform == "win32":
    extras_require["gssapi"] = ["winkerberos>=0.5.0"]
else:
    extras_require["gssapi"] = ["pykerberos"]

extra_opts = {"packages": ["bson", "pymongo", "gridfs"]}

if "--no_ext" in sys.argv:
    sys.argv.remove("--no_ext")
elif sys.platform.startswith("java") or sys.platform == "cli" or "PyPy" in sys.version:
    sys.stdout.write(
        """
*****************************************************\n
The optional C extensions are currently not supported\n
by this python implementation.\n
*****************************************************\n
"""
    )
else:
    extra_opts["ext_modules"] = ext_modules

setup(
    name="pymongo",
    version=version,
    description="Python driver for MongoDB <http://www.mongodb.org>",
    long_description=readme_content,
    author="The MongoDB Python Team",
    url="http://github.com/mongodb/mongo-python-driver",
    keywords=["mongo", "mongodb", "pymongo", "gridfs", "bson"],
    install_requires=[],
    license="Apache License, Version 2.0",
    python_requires=">=3.6.2",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Topic :: Database",
    ],
    cmdclass={"build_ext": custom_build_ext, "doc": doc, "test": test},
    extras_require=extras_require,
    **extra_opts
)
