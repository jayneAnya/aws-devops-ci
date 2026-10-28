# AWS environment setup

This document records the deployed CI environment for the project. It is
configured in `eu-north-1`; resource creation and build executions may incur
AWS charges.

## Resources

| Resource | Name |
|---|---|
| CodeCommit repository | `aws-devops-ci`, branch `main` |
| CodeBuild project | `aws-devops-ci-build` |
| CodePipeline pipeline | `aws-devops-ci-pipeline` |
| S3 artifact bucket | `aws-devops-ci-artifacts-657103446220-eu-north-1` |
| EventBridge source rule | `aws-devops-ci-source-main` |
| CodePipeline service role | `aws-devops-ci-codepipeline-role` |
| CodeBuild service role | `aws-devops-ci-codebuild-role` |

The CodeCommit source action provides the source artifact to CodeBuild.
CodeBuild uses the root `buildspec.yml`, runs the pytest suite, and returns a
build artifact to CodePipeline. The EventBridge rule triggers the pipeline
for creation or updates of the repository's `main` branch.

## IAM roles

The pipeline and build use separate service roles:

- `aws-devops-ci-codepipeline-role` trusts `codepipeline.amazonaws.com` for
  this pipeline. It can read the project's CodeCommit repository, start and
  inspect its CodeBuild project, access artifacts in the project's S3 bucket,
  and start the pipeline for its source EventBridge rule.
- `aws-devops-ci-codebuild-role` trusts `codebuild.amazonaws.com`. It can
  write this project's CloudWatch Logs and read/write the pipeline artifacts
  in the project's S3 bucket. It does not need CodeCommit permissions because
  CodePipeline supplies the source artifact.

The deployment identity is separate from both service roles. No AWS credentials
or secrets are stored in the repository. This sample requires no build
environment variables.

## Tags

The following project tags have been applied to the CodeCommit repository,
CodeBuild project, CodePipeline, S3 artifact bucket, EventBridge rule, and both
IAM roles:

| Key | Value |
|---|---|
| `Project` | `aws-devops-ci` |
| `Environment` | `learning` |
| `ManagedBy` | `student-project` |

These tags make ownership, cost attribution, and cleanup easier. AWS does not
charge for adding tags.

## CLI verification

Run these read-only commands with an authenticated AWS CLI profile:

```sh
aws sts get-caller-identity
aws codecommit get-branch \
  --repository-name aws-devops-ci \
  --branch-name main \
  --region eu-north-1
aws codepipeline list-pipeline-executions \
  --pipeline-name aws-devops-ci-pipeline \
  --region eu-north-1 \
  --max-results 5
aws codebuild list-builds-for-project \
  --project-name aws-devops-ci-build \
  --region eu-north-1 \
  --sort-order DESCENDING \
  --max-items 3
aws s3api list-objects-v2 \
  --bucket aws-devops-ci-artifacts-657103446220-eu-north-1 \
  --region eu-north-1
```

Verification performed for this submission:

- `aws sts get-caller-identity` succeeded for the configured AWS account. The
  account identifier is redacted here:

  ```json
  {
    "Account": "<AWS account ID>",
    "Arn": "arn:aws:iam::<AWS account ID>:user/aws-devops-lab-5"
  }
  ```

- Pipeline execution `a9a36eb0-4f01-41e7-8e6b-85fe3dd3928e` succeeded with both
  Source and Build stages succeeded.
- The associated CodeBuild run succeeded, including `INSTALL`, `BUILD`, and
  `UPLOAD_ARTIFACTS`.
- A generated artifact was present in the S3 artifact bucket. See the [S3
  artifact evidence](../screenshots/s3-artifact.jpg), [CodeBuild success
  evidence](../screenshots/codebuild-succeeded.jpg), and [CodeBuild test
  logs](../screenshots/codebuild-logs.jpg).

Screenshots are evidence from the AWS console. The console may display account
identifiers and resource names; do not include credentials, access keys, or
secret values in evidence.
