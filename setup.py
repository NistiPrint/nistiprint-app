from setuptools import setup, find_packages

setup(
    name="nistiprint-shared",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "SQLAlchemy>=2.0.0",
        "Flask-SQLAlchemy>=3.1.1",
        "supabase>=2.0.0",
        "python-dotenv>=1.0.0",
    ],
)
