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
        "requests>=2.25.0",
        "pandas>=1.5.0",
        "numpy>=1.20.0",
        "python-dateutil>=2.8.2",
        "pytz>=2023.3",
        "psycopg2-binary>=2.9.0",
        "google-cloud-secret-manager>=2.16.0",
        "google-generativeai>=0.3.0",
        "google-auth>=2.0.0",
        "celery[redis]>=5.3.0",
        "redis>=5.0.0",
    ],
)
