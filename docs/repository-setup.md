# Repository setup and branch workflow

The public submission repository is
[jayneAnya/aws-devops-ci](https://github.com/jayneAnya/aws-devops-ci). AWS
CodePipeline uses the separate CodeCommit repository `aws-devops-ci` in
`eu-north-1` as its source; pushing to GitHub alone does not trigger that
pipeline.

## Source repository

The project is stored in AWS CodeCommit and mirrored to GitHub:

- GitHub: `https://github.com/jayneAnya/aws-devops-ci`
- AWS CodeCommit: `aws-devops-ci`, branch `main`, region `eu-north-1`

The CodeCommit remote is named `codecommit` and the GitHub remote is named
`origin`. Do not add credentials to remote URLs or commit AWS credentials.

## Feature branch and review

Use a descriptive feature branch for changes, push it to GitHub, and open a
pull request to `main`. Review and merge the pull request before synchronizing
the updated `main` branch to CodeCommit, which is the AWS pipeline source.

```sh
git switch -c docs/submission-evidence
# Make and test the change
git add docs README.md buildspec.yml screenshots
git commit -m "docs: add AWS setup and submission evidence"
git push -u origin docs/submission-evidence
gh pr create --base main --head docs/submission-evidence
# Review and merge the pull request on GitHub
git switch main
git pull --ff-only origin main
git push codecommit main
```

For this update, the documentation and evidence are prepared on the
`docs/submission-evidence` feature branch for pull-request review. Once merged
to GitHub `main`, synchronize `main` to CodeCommit so CodePipeline runs the
updated source and packages the documentation and screenshots.

## Evidence included

- [Successful CodePipeline execution](../screenshots/codepipeline-succeeded.png)
- [Successful CodeBuild run](../screenshots/codebuild-succeeded.jpg)
- [CodeBuild pytest logs](../screenshots/codebuild-logs.jpg)
- [S3 build artifact](../screenshots/s3-artifact.jpg)
- [AWS environment and IAM configuration](./aws-environment-setup.md)
