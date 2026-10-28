# AWS DevOps CI Pipeline

A small Python application used to demonstrate a CI workflow with AWS
CodeCommit, CodeBuild, and CodePipeline. A push to the source branch starts a
pipeline; CodeBuild installs the test dependency, runs the tests, and packages
the application as a build artifact.

## Application

`app.py` provides a small addition function and a health status. `test_app.py`
contains the pytest checks run by CodeBuild.

Run the checks locally:

```sh
python -m pip install -r requirements.txt
python -m pytest -v
python app.py
```

## AWS setup

For a complete, repeatable CLI walkthrough—including IAM policies, artifact
bucket setup, pipeline creation, push triggers, verification, troubleshooting,
and cleanup—see the [AWS setup guide](./docs/aws-setup-guide.md).

The pipeline is configured in AWS region `eu-north-1` with these resources:

| Resource | Name or configuration |
|---|---|
| CodeCommit repository | `aws-devops-ci`, branch `main` |
| CodeBuild project | `aws-devops-ci-build`, `aws/codebuild/standard:7.0`, `BUILD_GENERAL1_SMALL` |
| CodePipeline | `aws-devops-ci-pipeline`, Source → Build |
| Artifact bucket | `aws-devops-ci-artifacts-657103446220-eu-north-1` (private, versioned, server-side encryption enabled) |
| Push trigger | EventBridge rule `aws-devops-ci-source-main`, scoped to updates to `main` |

The CodeCommit source action passes its output to CodeBuild, which uses this
repository's `buildspec.yml`. CodePipeline stores the build output in its S3
artifact bucket. The trigger starts the pipeline when the `main` branch is
created or updated.

### Service roles and permissions

The configured service roles are separate and scoped to this pipeline:

- **CodePipeline:** `aws-devops-ci-codepipeline-role` can read the specified
  CodeCommit repository, start and inspect the specified CodeBuild project,
  and access pipeline artifacts in the named S3 bucket. It can start this
  pipeline for the EventBridge trigger; the role trust is restricted to this
  pipeline and trigger.
- **CodeBuild:** `aws-devops-ci-codebuild-role` can write this project's
  CloudWatch Logs and read/write pipeline artifacts in the named S3 bucket.
  It does not need CodeCommit access because CodePipeline supplies the source.

This sample requires **no build environment variables**. Do not commit AWS
credentials or attach long-lived credentials to the project.

## Build and artifact

The root [buildspec.yml](./buildspec.yml) uses CodeBuild buildspec version 0.2
and Python 3.12. It installs `requirements.txt`, runs `pytest -v`, and executes
`app.py`. A test failure fails the build. The declared build artifact contains
the application, tests, dependency list, buildspec, this README, setup docs,
and AWS evidence screenshots. In a pipeline, CodePipeline transports the
CodeBuild action's output through its artifact bucket; the artifact is not
published as a deployed application.

## Submission checklist

- Submit the URL of your CodeCommit or GitHub repository (or an exported ZIP
  containing the source and `buildspec.yml`).
- The separate [AWS environment setup](./docs/aws-environment-setup.md)
  documents the actual resources, IAM role permissions, tags, and CLI
  verification commands.
- [Repository setup](./docs/repository-setup.md) documents the GitHub
  submission repository, CodeCommit pipeline source, and feature-branch
  workflow.
- AWS evidence is included in [`screenshots/`](./screenshots/): the successful
  pipeline, CodeBuild run, and S3 build artifact.

This sample uses no build environment variables. Do not include credentials or
other secrets in the repository or screenshots.
