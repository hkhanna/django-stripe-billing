import setuptools
from pathlib import Path

long_description = (Path(__file__).parent / "README.md").read_text()

setuptools.setup(
    name="django-stripe-billing",
    author="Harry Khanna",
    author_email="harry@khanna.cc",
    description="Django billing plans and payments with Stripe",
    long_description=long_description,
    long_description_content_type="text/markdown",
    license="MIT",
    url="https://github.com/hkhanna/django-stripe-billing",
    packages=setuptools.find_packages(),
    install_requires=["Django", "stripe==2.*"],
    python_requires=">=3.8",
    classifiers=[
        "Framework :: Django",
        "Programming Language :: Python",
        "Intended Audience :: Developers",
    ],
)
