# AWS DevOps CI Pipeline

## Overview
A Python application demonstrating continuous integration
using AWS CodePipeline and AWS CodeBuild.

## Build and test locally
pip install -r requirements.txt
pytest -v
python app.py

## AWS architecture
Source repository -> CodePipeline -> CodeBuild -> S3 artifact

## Security
AWS service roles should follow least-privilege principles.
Do not commit AWS credentials or secrets to this repository.

## Build configuration
The build is defined in buildspec.yml and uses Python 3.12.
Pytest validates the application before the build succeeds.
