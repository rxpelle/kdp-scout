from setuptools import setup, find_packages

setup(
    name='kdp-scout',
    version='0.2.0',
    description='Amazon KDP keyword research and competitor analysis tool',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    author='KDP Scout Contributors',
    url='https://github.com/rxpelle/kdp-scout',
    license='MIT',
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
    extras_require={
        'dev': [
            'pytest',
            'pytest-cov',
        ],
    },
    entry_points={
        'console_scripts': [
            'kdp-scout=kdp_scout.cli:main',
        ],
    },
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Office/Business',
    ],
)
