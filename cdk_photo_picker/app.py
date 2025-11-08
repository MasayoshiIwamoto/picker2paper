#!/usr/bin/env python3
import os
import aws_cdk as cdk

from photo_picker.cert_stack import PhotoPickerCertStack
from photo_picker.app_stack import PhotoPickerAppStack


app = cdk.App()

# Context defaults from cdk.json
domain_name = app.node.try_get_context("domainName")
hosted_zone_name = app.node.try_get_context("hostedZoneName")
site_bucket_name = app.node.try_get_context("siteBucketName")
uploads_bucket_name = app.node.try_get_context("uploadsBucketName")
cloudfront_certificate_arn = app.node.try_get_context("cloudFrontCertificateArn")

# Resolve env (account/region) for context lookups
default_account = os.getenv("CDK_DEFAULT_ACCOUNT")
default_region = os.getenv("CDK_DEFAULT_REGION") or "ap-northeast-1"

# Stacks
cert_stack = None
if not cloudfront_certificate_arn and domain_name and hosted_zone_name:
    cert_stack = PhotoPickerCertStack(
        app,
        "PhotoPickerCertStack",
        domain_name=domain_name,
        hosted_zone_name=hosted_zone_name,
        env=cdk.Environment(account=default_account, region="us-east-1"),
        description="ACM certificate for CloudFront (us-east-1)",
    )
    cloudfront_certificate_arn = cert_stack.certificate_arn

app_stack = PhotoPickerAppStack(
    app,
    "PhotoPickerAppStack",
    domain_name=domain_name,
    hosted_zone_name=hosted_zone_name,
    site_bucket_name=site_bucket_name,
    uploads_bucket_name=uploads_bucket_name,
    certificate_arn=cloudfront_certificate_arn,
    env=cdk.Environment(account=default_account, region=default_region),
    description="PhotoPicker Web Upload Stack: Site hosting + presign/manage APIs",
)

if cert_stack:
    app_stack.add_dependency(cert_stack)

cdk.Tags.of(app_stack).add("App", "PhotoPickerApp")
if cert_stack:
    cdk.Tags.of(cert_stack).add("App", "PhotoPickerApp")

app.synth()
