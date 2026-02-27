from setuptools import setup, find_packages

setup(
    name='kdp-scout',
    version='0.1.0',
    description='Amazon KDP keyword research and competitor analysis tool',
    author='Randy Pellegrini',
    packages=find_packages(),
    python_requires='>=3.9',
    install_requires=[
        'requests',
        'beautifulsoup4',
        'click',
        'rich',
        'python-dotenv',
        'pandas',
    ],
    entry_points={
        'console_scripts': [
            'kdp-scout=kdp_scout.cli:main',
        ],
    },
)
