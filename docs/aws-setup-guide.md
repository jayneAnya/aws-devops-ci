# Re-create the AWS CI pipeline

This guide recreates the sample CI pipeline in your own AWS account using the
AWS CLI. It is written for the Python app in this repository and creates:

- A CodeCommit repository and `main` branch (if you do not already have one).
- A private, versioned S3 artifact bucket.
- Separate CodeBuild and CodePipeline IAM service roles.
- A CodeBuild project and a two-stage CodePipeline.
- An EventBridge rule that starts the pipeline when `main` changes.

The pipeline runs tests and packages an artifact. It does not deploy the app.
AWS resources can incur charges. Use an AWS account and region you control,
and delete the resources when finished. Do not paste credentials into this
guide, commit them, or send them in chat.

## 1. Prerequisites

Install and configure AWS CLI v2, Git, and Python 3.12. Authenticate using an
AWS profile, IAM Identity Center/SSO, or your organization's approved
credential provider. The identity needs permission to create the listed
resources, configure IAM policies and trust relationships, pass the service
roles, and push to CodeCommit.

For example, authenticate with IAM Identity Center:

```sh
aws configure sso
aws sso login --profile dev
export AWS_PROFILE=dev
```

Choose a region that supports CodeCommit, CodeBuild, CodePipeline, EventBridge,
and S3. Set the region and confirm your identity:

```sh
export AWS_DEFAULT_REGION=eu-north-1
aws sts get-caller-identity
```

Use the returned account ID to check that you are in the intended account.
The commands below derive the account ID instead of hard-coding it.

## 2. Set names and create the source repository

Set names for this project. S3 bucket names are globally unique, so include
your account ID and region or another unique suffix.

```sh
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-eu-north-1}"
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export PROJECT="aws-devops-ci"
export REPOSITORY="$PROJECT"
export BUILD_PROJECT="$PROJECT-build"
export PIPELINE="$PROJECT-pipeline"
export CODEBUILD_ROLE="$PROJECT-codebuild-role"
export CODEPIPELINE_ROLE="$PROJECT-codepipeline-role"
export EVENT_RULE="$PROJECT-source-main"
export ARTIFACT_BUCKET="${PROJECT}-artifacts-${ACCOUNT_ID}-${AWS_DEFAULT_REGION}"
export PIPELINE_ARN="arn:aws:codepipeline:${AWS_DEFAULT_REGION}:${ACCOUNT_ID}:${PIPELINE}"
export CODEBUILD_ARN="arn:aws:codebuild:${AWS_DEFAULT_REGION}:${ACCOUNT_ID}:project/${BUILD_PROJECT}"
export REPOSITORY_ARN="arn:aws:codecommit:${AWS_DEFAULT_REGION}:${ACCOUNT_ID}:${REPOSITORY}"
export EVENT_RULE_ARN="arn:aws:events:${AWS_DEFAULT_REGION}:${ACCOUNT_ID}:rule/${EVENT_RULE}"
export CODEBUILD_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${CODEBUILD_ROLE}"
export CODEPIPELINE_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${CODEPIPELINE_ROLE}"
```

Create the repository if you do not already have it:

```sh
aws codecommit create-repository \
  --repository-name "$REPOSITORY" \
  --repository-description "Python application for AWS CodePipeline and CodeBuild"
```

If it already exists, skip creation and verify its name and region:

```sh
aws codecommit get-repository \
  --repository-name "$REPOSITORY" \
  --query 'repositoryMetadata.{name:repositoryName,arn:Arn,defaultBranch:defaultBranch}' \
  --output table
```

Clone it, or add it as a remote to this existing Git working tree:

```sh
git remote add codecommit \
  "https://git-codecommit.${AWS_DEFAULT_REGION}.amazonaws.com/v1/repos/${REPOSITORY}"
git config --local credential.helper \
  '!aws codecommit credential-helper $@'
git config --local credential.UseHttpPath true
```

If the `codecommit` remote already exists, do not add it again. Confirm the
remote points to the intended repository:

```sh
git remote -v
```

Commit and push the source files, including the root `buildspec.yml`, to
`main`. If this repository already has a commit, preserve its history instead
of initializing or force-pushing over it.

```sh
git add app.py test_app.py requirements.txt buildspec.yml README.md
git commit -m "build: add application and CodeBuild specification"
git push -u codecommit main
```

Confirm the branch exists:

```sh
aws codecommit get-branch \
  --repository-name "$REPOSITORY" \
  --branch-name main
```

## 3. Create and secure the artifact bucket

Create the bucket in the selected region. The Stockholm region needs a
`LocationConstraint`; the command below covers that region.

```sh
aws s3api create-bucket \
  --bucket "$ARTIFACT_BUCKET" \
  --region "$AWS_DEFAULT_REGION" \
  --create-bucket-configuration "LocationConstraint=${AWS_DEFAULT_REGION}"
```

For `us-east-1`, omit `--create-bucket-configuration`:

```sh
aws s3api create-bucket --bucket "$ARTIFACT_BUCKET" --region us-east-1
```

Block public access, enable default encryption, and version the bucket:

```sh
aws s3api put-public-access-block \
  --bucket "$ARTIFACT_BUCKET" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-encryption \
  --bucket "$ARTIFACT_BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api put-bucket-versioning \
  --bucket "$ARTIFACT_BUCKET" \
  --versioning-configuration Status=Enabled
```

## 4. Create the CodeBuild role

The CodeBuild role only needs CloudWatch Logs access and S3 access to the
pipeline artifact bucket. It does not need CodeCommit permissions because the
CodePipeline source action passes the source artifact to the build.

Create a role trusted by CodeBuild:

```sh
cat > /tmp/codebuild-trust.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "codebuild.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
JSON

aws iam create-role \
  --role-name "$CODEBUILD_ROLE" \
  --assume-role-policy-document file:///tmp/codebuild-trust.json \
  --description "CodeBuild role for ${PROJECT}"
```

Add a scoped inline policy for this build's logs and artifacts:

```sh
cat > /tmp/codebuild-access.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup"],
      "Resource": "arn:aws:logs:${AWS_DEFAULT_REGION}:${ACCOUNT_ID}:log-group:/aws/codebuild/${BUILD_PROJECT}"
    },
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:${AWS_DEFAULT_REGION}:${ACCOUNT_ID}:log-group:/aws/codebuild/${BUILD_PROJECT}:log-stream:*"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetBucketAcl", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::${ARTIFACT_BUCKET}"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"],
      "Resource": "arn:aws:s3:::${ARTIFACT_BUCKET}/*"
    }
  ]
}
JSON

aws iam put-role-policy \
  --role-name "$CODEBUILD_ROLE" \
  --policy-name "${PROJECT}-codebuild-access" \
  --policy-document file:///tmp/codebuild-access.json
```

If you change artifact storage to a customer-managed KMS key, add only the
required `kms:Decrypt`, `kms:Encrypt`, `kms:GenerateDataKey`, and
`kms:DescribeKey` permissions for that key to the roles that use the bucket.
The sample uses S3-managed encryption and does not require a custom KMS key.

## 5. Create the CodePipeline role

The pipeline role needs to read the selected CodeCommit repository, start and
inspect the selected CodeBuild project, and read/write this pipeline's S3
artifacts.

Create its trust policy. The EventBridge trust statement allows only the
specific source rule to assume the role:

```sh
cat > /tmp/codepipeline-trust.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "codepipeline.amazonaws.com"},
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {"aws:SourceAccount": "${ACCOUNT_ID}"},
        "ArnEquals": {"aws:SourceArn": "${PIPELINE_ARN}"}
      }
    },
    {
      "Effect": "Allow",
      "Principal": {"Service": "events.amazonaws.com"},
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {"aws:SourceAccount": "${ACCOUNT_ID}"},
        "ArnEquals": {"aws:SourceArn": "${EVENT_RULE_ARN}"}
      }
    }
  ]
}
JSON

aws iam create-role \
  --role-name "$CODEPIPELINE_ROLE" \
  --assume-role-policy-document file:///tmp/codepipeline-trust.json \
  --description "CodePipeline role for ${PROJECT}"
```

Add its scoped permissions:

```sh
cat > /tmp/codepipeline-access.json <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "codecommit:GetBranch",
        "codecommit:GetCommit",
        "codecommit:GetRepository",
        "codecommit:GetUploadArchiveStatus",
        "codecommit:UploadArchive",
        "codecommit:CancelUploadArchive"
      ],
      "Resource": "${REPOSITORY_ARN}"
    },
    {
      "Effect": "Allow",
      "Action": ["codebuild:StartBuild", "codebuild:BatchGetBuilds"],
      "Resource": "${CODEBUILD_ARN}"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketAcl",
        "s3:GetBucketLocation",
        "s3:GetBucketVersioning",
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::${ARTIFACT_BUCKET}"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"],
      "Resource": "arn:aws:s3:::${ARTIFACT_BUCKET}/*"
    },
    {
      "Effect": "Allow",
      "Action": ["codepipeline:StartPipelineExecution"],
      "Resource": "${PIPELINE_ARN}"
    }
  ]
}
JSON

aws iam put-role-policy \
  --role-name "$CODEPIPELINE_ROLE" \
  --policy-name "${PROJECT}-codepipeline-access" \
  --policy-document file:///tmp/codepipeline-access.json
```

The user or automation identity running setup also needs `iam:PassRole` on
these two exact role ARNs for the respective AWS services. Do not give the
build or pipeline `AdministratorAccess`.

## 6. Create the CodeBuild project

This uses the managed Ubuntu standard image, which supports the sample's
Python 3.12 buildspec and small compute size:

```sh
aws codebuild create-project \
  --region "$AWS_DEFAULT_REGION" \
  --name "$BUILD_PROJECT" \
  --description "Test and package ${PROJECT}" \
  --source type=CODEPIPELINE,buildspec=buildspec.yml \
  --artifacts type=CODEPIPELINE \
  --environment type=LINUX_CONTAINER,image=aws/codebuild/standard:7.0,computeType=BUILD_GENERAL1_SMALL,imagePullCredentialsType=CODEBUILD \
  --service-role "$CODEBUILD_ROLE_ARN" \
  --timeout-in-minutes 15 \
  --queued-timeout-in-minutes 60
```

`buildspec.yml` installs requirements, runs `pytest -v`, runs the sample
application, then declares the files to package. Pipeline-provided artifacts
are intentional: CodePipeline supplies the source and receives the build
artifact.

Apply consistent project tags:

```sh
aws codecommit tag-resource \
  --region "$AWS_DEFAULT_REGION" \
  --resource-arn "$REPOSITORY_ARN" \
  --tags '{"Project":"aws-devops-ci","Environment":"learning","ManagedBy":"student-project"}'

aws codebuild update-project \
  --region "$AWS_DEFAULT_REGION" \
  --name "$BUILD_PROJECT" \
  --tags key=Project,value=aws-devops-ci key=Environment,value=learning key=ManagedBy,value=student-project

aws iam tag-role --role-name "$CODEBUILD_ROLE" \
  --tags Key=Project,Value=aws-devops-ci Key=Environment,Value=learning Key=ManagedBy,Value=student-project
aws iam tag-role --role-name "$CODEPIPELINE_ROLE" \
  --tags Key=Project,Value=aws-devops-ci Key=Environment,Value=learning Key=ManagedBy,Value=student-project
aws s3api put-bucket-tagging \
  --bucket "$ARTIFACT_BUCKET" \
  --tagging 'TagSet=[{Key=Project,Value=aws-devops-ci},{Key=Environment,Value=learning},{Key=ManagedBy,Value=student-project}]'
```

## 7. Create the pipeline

Create a pipeline with a CodeCommit source action followed by a CodeBuild
action. `PollForSourceChanges` is false because the next step configures an
EventBridge push trigger.

```sh
cat > /tmp/pipeline.json <<JSON
{
  "pipeline": {
    "name": "${PIPELINE}",
    "roleArn": "${CODEPIPELINE_ROLE_ARN}",
    "artifactStore": {
      "type": "S3",
      "location": "${ARTIFACT_BUCKET}"
    },
    "stages": [
      {
        "name": "Source",
        "actions": [{
          "name": "Source",
          "actionTypeId": {
            "category": "Source",
            "owner": "AWS",
            "provider": "CodeCommit",
            "version": "1"
          },
          "runOrder": 1,
          "configuration": {
            "RepositoryName": "${REPOSITORY}",
            "BranchName": "main",
            "PollForSourceChanges": "false"
          },
          "outputArtifacts": [{"name": "SourceOutput"}],
          "region": "${AWS_DEFAULT_REGION}",
          "namespace": "SourceVariables"
        }]
      },
      {
        "name": "Build",
        "actions": [{
          "name": "Build",
          "actionTypeId": {
            "category": "Build",
            "owner": "AWS",
            "provider": "CodeBuild",
            "version": "1"
          },
          "runOrder": 1,
          "configuration": {"ProjectName": "${BUILD_PROJECT}"},
          "inputArtifacts": [{"name": "SourceOutput"}],
          "outputArtifacts": [{"name": "BuildArtifact"}],
          "region": "${AWS_DEFAULT_REGION}"
        }]
      }
    ]
  }
}
JSON

aws codepipeline create-pipeline \
  --region "$AWS_DEFAULT_REGION" \
  --cli-input-json file:///tmp/pipeline.json

aws codepipeline tag-resource \
  --region "$AWS_DEFAULT_REGION" \
  --resource-arn "$PIPELINE_ARN" \
  --tags key=Project,value=aws-devops-ci key=Environment,value=learning key=ManagedBy,value=student-project
```

## 8. Configure automatic push detection

Create an EventBridge rule for updates and creation of the `main` branch, then
target the pipeline using its service role:

```sh
aws events put-rule \
  --region "$AWS_DEFAULT_REGION" \
  --name "$EVENT_RULE" \
  --description "Start ${PIPELINE} when ${REPOSITORY}/main changes" \
  --state ENABLED \
  --event-pattern "{\"source\":[\"aws.codecommit\"],\"detail-type\":[\"CodeCommit Repository State Change\"],\"resources\":[\"${REPOSITORY_ARN}\"],\"detail\":{\"event\":[\"referenceCreated\",\"referenceUpdated\"],\"referenceType\":[\"branch\"],\"referenceName\":[\"main\"]}}"
```

Add the target:

```sh
cat > /tmp/event-target.json <<JSON
[
  {
    "Id": "${PIPELINE}",
    "Arn": "${PIPELINE_ARN}",
    "RoleArn": "${CODEPIPELINE_ROLE_ARN}"
  }
]
JSON

aws events put-targets \
  --region "$AWS_DEFAULT_REGION" \
  --rule "$EVENT_RULE" \
  --targets file:///tmp/event-target.json

aws events tag-resource \
  --region "$AWS_DEFAULT_REGION" \
  --resource-arn "$EVENT_RULE_ARN" \
  --tags Key=Project,Value=aws-devops-ci Key=Environment,Value=learning Key=ManagedBy,Value=student-project
```

`FailedEntryCount` must be `0`. If it is not, inspect the failure details before
testing. The EventBridge rule and the CodePipeline role trust policy must use
the same rule ARN and account ID.

## 9. Run and verify the pipeline

Start an initial run:

```sh
aws codepipeline start-pipeline-execution \
  --region "$AWS_DEFAULT_REGION" \
  --name "$PIPELINE"
```

Check stages:

```sh
aws codepipeline get-pipeline-state \
  --region "$AWS_DEFAULT_REGION" \
  --name "$PIPELINE" \
  --query 'stageStates[].{stage:stageName,status:latestExecution.status}' \
  --output table
```

Both `Source` and `Build` should show `Succeeded`. To inspect execution
history, build logs, and artifact paths:

```sh
aws codepipeline list-pipeline-executions \
  --region "$AWS_DEFAULT_REGION" \
  --pipeline-name "$PIPELINE" \
  --max-results 5

aws codebuild list-builds-for-project \
  --region "$AWS_DEFAULT_REGION" \
  --project-name "$BUILD_PROJECT" \
  --sort-order DESCENDING \
  --max-items 5

aws codebuild batch-get-builds \
  --region "$AWS_DEFAULT_REGION" \
  --ids <build-id-from-the-previous-command>

aws s3api list-objects-v2 \
  --region "$AWS_DEFAULT_REGION" \
  --bucket "$ARTIFACT_BUCKET"
```

To prove the change trigger works, push a commit to the CodeCommit `main`
branch. A new execution should report a CloudWatch/EventBridge trigger and the
new source commit. If using a GitHub mirror and feature branches, review and
merge the pull request to GitHub `main`, then push that merged `main` commit to
the CodeCommit remote; CodePipeline watches CodeCommit, not GitHub.

## 10. Capture submission evidence

Capture evidence from your own AWS account, after a successful run:

1. **Pipeline:** open CodePipeline → your pipeline and show the same execution
   with successful Source and Build stages.
2. **Build logs:** open the associated CodeBuild build. Capture its `Succeeded`
   status and the build log showing the pytest results and successful artifact
   upload.
3. **Artifact:** open the S3 artifact bucket and show a CodePipeline
   `BuildArtif` object and its details. Pipeline artifact object keys are
   generated and can change on each run.
4. Include this setup guide, the repository guide, the root `buildspec.yml`,
   and your repository URL in the submission.

Do not expose access keys, secret values, session tokens, or other credentials
in screenshots. The sample does not need build environment variables.

## 11. Troubleshooting

### AWS identity or authorization errors

- `InvalidClientTokenId`, `ExpiredToken`, or `Unable to locate credentials`:
  re-authenticate the selected profile (for SSO, run `aws sso login --profile
  <profile>`) and confirm `aws sts get-caller-identity`.
- `AccessDenied` during setup: the setup identity needs permission for the
  failed operation and `iam:PassRole` on the exact service roles. Ask your
  administrator for the minimum missing permissions; do not attach
  `AdministratorAccess` to CodeBuild or CodePipeline.
- `AccessDenied` inside a build or pipeline: inspect the service role policy,
  trust relationship, target resource ARN, region, account ID, and S3 bucket
  policy. A role's trust policy controls who can assume it; its permissions
  policy controls what the assumed role can do.

### CodeCommit source cannot be fetched

- Confirm the repository exists in the same region as the source action, the
  branch name is exactly `main`, and the pushed branch has a commit.
- Check the pipeline role has the CodeCommit read/archive actions on the
  repository ARN.
- When using Git over HTTPS, configure the AWS CodeCommit credential helper
  and ensure the local AWS identity can access CodeCommit.
- Check whether a push went to GitHub instead of the `codecommit` remote.
  GitHub changes do not trigger this pipeline unless a separate GitHub source
  integration is configured.

### EventBridge does not trigger a run

- Verify the rule is `ENABLED`, matches the repository ARN and `main` branch,
  and has the pipeline as a target.
- Confirm `put-targets` returned `FailedEntryCount: 0`.
- Confirm the CodePipeline role trust policy includes
  `events.amazonaws.com` with the exact EventBridge rule ARN and account ID.
- Ensure `PollForSourceChanges` is false when using this event rule; enabling
  both polling and an event rule can result in duplicate runs.
- Wait briefly after a push, then inspect the pipeline execution list.

### CodeBuild fails to start or cannot read the artifact

- Confirm the build project source and artifacts are both `CODEPIPELINE`.
- Confirm the pipeline's Build action points to the correct build project and
  passes `SourceOutput` as its input artifact.
- Confirm the CodeBuild service role trusts `codebuild.amazonaws.com` and can
  read/write the pipeline artifact bucket and write its CloudWatch Logs group.
- Check the pipeline role has `codebuild:StartBuild` and
  `codebuild:BatchGetBuilds` on the build project ARN.
- If using a custom image, check its compatibility with the chosen environment
  type and compute size. The managed `aws/codebuild/standard:7.0` image is
  compatible with `BUILD_GENERAL1_SMALL`; some Amazon Linux images are not.

### The buildspec, dependency install, or tests fail

- Confirm `buildspec.yml` is at the repository root and valid YAML.
- Check the configured runtime exists in the selected CodeBuild image.
- Review the `INSTALL` and `BUILD` sections in CodeBuild logs. The sample needs
  network access to install the `pytest` dependency from `requirements.txt`.
- Run `.venv/bin/python -m pytest -v` locally. A nonzero test exit code
  correctly fails the CodeBuild build.
- Ensure artifact paths exist. CodeBuild fails artifact upload if required
  files cannot be found.

### The artifact bucket cannot be deleted

S3 buckets with versioning enabled retain object versions and delete markers.
Deleting current object names with `aws s3 rm --recursive` is not sufficient.
Use the version-aware purge in the cleanup section before deleting the bucket.

## 12. Tear down resources

Deleting pipeline resources does not delete the CodeCommit repository or its
Git history. Decide separately whether you want to retain or delete that
repository. The following removes only resources named for this project in
this region.

Check for running executions first. Do not delete the pipeline while an
execution is still in progress:

```sh
aws codepipeline list-pipeline-executions \
  --region "$AWS_DEFAULT_REGION" \
  --pipeline-name "$PIPELINE" \
  --max-results 10
```

Delete the pipeline, build project, event target/rule, and build logs:

```sh
aws codepipeline delete-pipeline \
  --region "$AWS_DEFAULT_REGION" \
  --name "$PIPELINE"

aws codebuild delete-project \
  --region "$AWS_DEFAULT_REGION" \
  --name "$BUILD_PROJECT"

aws events remove-targets \
  --region "$AWS_DEFAULT_REGION" \
  --rule "$EVENT_RULE" \
  --ids "$PIPELINE"
aws events delete-rule \
  --region "$AWS_DEFAULT_REGION" \
  --name "$EVENT_RULE"

aws logs delete-log-group \
  --region "$AWS_DEFAULT_REGION" \
  --log-group-name "/aws/codebuild/${BUILD_PROJECT}"
```

Delete the two inline policies and service roles after the pipeline and
project are deleted:

```sh
aws iam delete-role-policy \
  --role-name "$CODEBUILD_ROLE" \
  --policy-name "${PROJECT}-codebuild-access"
aws iam delete-role --role-name "$CODEBUILD_ROLE"

aws iam delete-role-policy \
  --role-name "$CODEPIPELINE_ROLE" \
  --policy-name "${PROJECT}-codepipeline-access"
aws iam delete-role --role-name "$CODEPIPELINE_ROLE"
```

If you enabled bucket versioning, permanently delete every object version and
delete marker before deleting the bucket. This Python 3 script uses the AWS
CLI paginator, deletes in batches of 1,000, and refuses to continue if any
deletion fails:

```sh
python3 - "$ARTIFACT_BUCKET" "$AWS_DEFAULT_REGION" <<'PY'
import json
import subprocess
import sys

bucket, region = sys.argv[1:3]
listing = subprocess.run(
    [
        "aws", "s3api", "list-object-versions",
        "--bucket", bucket,
        "--region", region,
        "--output", "json",
    ],
    check=True,
    capture_output=True,
    text=True,
)
inventory = json.loads(listing.stdout)
objects = [
    {"Key": item["Key"], "VersionId": item["VersionId"]}
    for field in ("Versions", "DeleteMarkers")
    for item in inventory.get(field, [])
]

for offset in range(0, len(objects), 1000):
    batch = {"Objects": objects[offset:offset + 1000], "Quiet": True}
    result = subprocess.run(
        [
            "aws", "s3api", "delete-objects",
            "--bucket", bucket,
            "--region", region,
            "--delete", json.dumps(batch),
            "--output", "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    errors = json.loads(result.stdout).get("Errors", [])
    if errors:
        raise SystemExit(f"Object deletion failed: {errors}")

print(f"Deleted {len(objects)} object versions/delete markers from {bucket}")
PY

aws s3api delete-bucket \
  --bucket "$ARTIFACT_BUCKET" \
  --region "$AWS_DEFAULT_REGION"
```

Remove only the tags added to the existing repository. Keep the repository
unless you intentionally want to permanently delete its source and history:

```sh
aws codecommit untag-resource \
  --region "$AWS_DEFAULT_REGION" \
  --resource-arn "$REPOSITORY_ARN" \
  --tag-keys Project Environment ManagedBy
```

To remove the CodeCommit repository as a separate, destructive choice, first
confirm that neither you nor another pipeline needs it:

```sh
aws codecommit delete-repository \
  --region "$AWS_DEFAULT_REGION" \
  --repository-name "$REPOSITORY"
```

Deleting the repository is irreversible from AWS; retain a Git mirror or
backup before running that command if the source history matters.

Finally verify cleanup:

```sh
aws codepipeline list-pipelines --region "$AWS_DEFAULT_REGION"
aws codebuild list-projects --region "$AWS_DEFAULT_REGION"
aws events list-rules --region "$AWS_DEFAULT_REGION" --name-prefix "$PROJECT"
aws iam get-role --role-name "$CODEBUILD_ROLE"
aws iam get-role --role-name "$CODEPIPELINE_ROLE"
aws s3api head-bucket --bucket "$ARTIFACT_BUCKET"
```

The last commands for deleted roles and buckets should report that the
resources do not exist. Keep the CodeCommit repository verification separate
if you chose to retain it.
