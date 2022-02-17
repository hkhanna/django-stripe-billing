import setuptools

setuptools.setup(
    name="django-stripe-billing",
    version="0.3.6",
    author="Harry Khanna",
    author_email="harry@khanna.cc",
    description="Django billing plans and payments with Stripe",
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
