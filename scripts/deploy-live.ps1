[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet("development", "production")]
    [string] $Environment,

    [Parameter(Mandatory)]
    [string] $AlexaSkillId,

    [string] $AwsProfile,
    [string] $Region = "eu-west-1",
    [string] $EcrRepository = "hear-python",
    [string] $HearApiUrl = "https://alexa.hear.media/api/v1",
    [string] $HearApiPathPrefix = "alexa",
    [string] $WebhookOutboundUrl = "https://alexa.hear.media/api/v1/alexa/events",
    [switch] $ConfirmProduction
)

$ErrorActionPreference = "Stop"

if ($Environment -eq "production" -and -not $ConfirmProduction) {
    throw "Production deployment requires -ConfirmProduction."
}

foreach ($command in @("aws", "docker", "sam")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command '$command' is not installed or not available on PATH."
    }
}

$awsArgs = @()
if ($AwsProfile) {
    $awsArgs += @("--profile", $AwsProfile)
}

function Invoke-Aws {
    param([Parameter(ValueFromRemainingArguments)] [string[]] $Arguments)
    & aws @awsArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "AWS CLI command failed: aws $($Arguments -join ' ')"
    }
}

function Get-SsmParameter {
    param([string] $Name, [switch] $Optional)
    $result = & aws @awsArgs ssm get-parameter --name $Name --with-decryption `
        --query "Parameter.Value" --output text --region $Region 2>$null
    if ($LASTEXITCODE -ne 0) {
        if ($Optional) { return "" }
        throw "Required SSM parameter '$Name' could not be read."
    }
    return $result.Trim()
}

$shortStage = if ($Environment -eq "production") { "prod" } else { "dev" }
$logLevel = if ($Environment -eq "production") { "INFO" } else { "DEBUG" }
$parameterPrefix = "/hear/$Environment"
$imageTag = "$Environment-$((Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss'))"

$accountId = (Invoke-Aws sts get-caller-identity --query Account --output text).Trim()
$registry = "$accountId.dkr.ecr.$Region.amazonaws.com"
$imageUri = "$registry/$EcrRepository`:$imageTag"

Write-Host "Deploying current code to $Environment as $imageUri"

$null = & aws @awsArgs ecr describe-repositories --repository-names $EcrRepository --region $Region 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-Aws ecr create-repository --repository-name $EcrRepository --region $Region | Out-Null
}

$loginPassword = Invoke-Aws ecr get-login-password --region $Region
$loginPassword | & docker login --username AWS --password-stdin $registry
if ($LASTEXITCODE -ne 0) { throw "Docker ECR login failed." }

& docker build --platform linux/amd64 --provenance=false -t $imageUri .
if ($LASTEXITCODE -ne 0) { throw "Docker build failed." }
& docker push $imageUri
if ($LASTEXITCODE -ne 0) { throw "Docker push failed." }

$hearApiKey = Get-SsmParameter "$parameterPrefix/HEAR_API_KEY"
$webhookOutboundSecret = Get-SsmParameter "$parameterPrefix/WEBHOOK_OUTBOUND_SECRET" -Optional
$sentryDsn = Get-SsmParameter "$parameterPrefix/SENTRY_DSN" -Optional

$parameterOverrides = @(
    "Stage=$Environment",
    "ShortStage=$shortStage",
    "ImageUri=$imageUri",
    "AlexaSkillId=$AlexaSkillId",
    "HearApiUrl=$HearApiUrl",
    "HearApiPathPrefix=$HearApiPathPrefix",
    "HearApiKey=$hearApiKey",
    "WebhookOutboundUrl=$WebhookOutboundUrl",
    "WebhookOutboundSecret=$webhookOutboundSecret",
    "SentryDsn=$sentryDsn",
    "PowerToolsLogLevel=$logLevel"
)

$samArgs = @(
    "deploy",
    "--config-file", "samconfig.toml",
    "--config-env", $Environment,
    "--region", $Region,
    "--parameter-overrides"
) + $parameterOverrides
if ($AwsProfile) {
    $samArgs += @("--profile", $AwsProfile)
}
if ($Environment -eq "production") {
    $samArgs += "--confirm-changeset"
} else {
    $samArgs += "--no-confirm-changeset"
}

& sam @samArgs
if ($LASTEXITCODE -ne 0) { throw "SAM deployment failed." }

$stackName = if ($Environment -eq "production") { "hear-py-prod" } else { "hear-py-development" }
$functionArn = (Invoke-Aws cloudformation describe-stacks --stack-name $stackName `
    --region $Region --query "Stacks[0].Outputs[?OutputKey=='SkillFunctionArn'].OutputValue | [0]" `
    --output text).Trim()

$responseFile = Join-Path ([System.IO.Path]::GetTempPath()) "hear-$Environment-resolver-health.json"
Invoke-Aws lambda invoke --function-name $functionArn --region $Region `
    --cli-binary-format raw-in-base64-out --payload '{"diagnostic":"resolver"}' $responseFile | Out-Null

$response = Get-Content -Raw $responseFile | ConvertFrom-Json
if (-not $response.ok) {
    throw "Live Lambda resolver diagnostic failed: $(Get-Content -Raw $responseFile)"
}

Write-Host "Live Lambda test passed for $Environment ($functionArn)."
Write-Host "Resolver returned canonical value '$($response.canonicalValue)'."
