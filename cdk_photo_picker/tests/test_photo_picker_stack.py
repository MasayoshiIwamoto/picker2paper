import sys
from pathlib import Path
from typing import Any, Dict, Tuple

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from photo_picker.app_stack import PhotoPickerAppStack
except ModuleNotFoundError:
    PhotoPickerAppStack = None  # type: ignore[assignment]

pytestmark = pytest.mark.skipif(
    PhotoPickerAppStack is None,
    reason="photo_picker/app_stack.py is not available yet. Add the stack module to run these tests.",
)


def synthesize_stack(
    context: Dict[str, Any] | None = None,
    **stack_kwargs: Any,
) -> Tuple["PhotoPickerAppStack", Template]:
    app = cdk.App(context=context or {})
    stack = PhotoPickerAppStack(app, "PhotoPickerAppStackTest", **stack_kwargs)
    template = Template.from_stack(stack)
    return stack, template


def test_stack_synthesizes_core_resources() -> None:
    _, template = synthesize_stack()

    template.resource_count_is("AWS::S3::Bucket", 2)
    template.resource_count_is("AWS::Lambda::Function", 2)
    template.resource_count_is("AWS::ApiGateway::RestApi", 1)
    template.resource_count_is("AWS::CloudFront::Distribution", 1)
    template.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)


def test_lambda_environment_uses_domain_for_cors() -> None:
    _, template = synthesize_stack(domain_name="uploads.example.com")

    functions = template.find_resources("AWS::Lambda::Function")
    assert functions, "Expected presign/manage Lambda functions to be defined"

    envs = [props["Properties"]["Environment"]["Variables"] for props in functions.values()]
    for env in envs:
        assert env["ALLOW_ORIGIN"] == "https://uploads.example.com"
        assert "UPLOAD_BUCKET" in env

    manage_env = next(env for env in envs if "UPLOAD_PREFIX" in env)
    assert manage_env["UPLOAD_PREFIX"] == "uploads/"
    assert manage_env["PROCESSED_PREFIX"] == "processed/"


def test_outputs_include_api_endpoints() -> None:
    _, template = synthesize_stack()
    outputs = template.to_json().get("Outputs", {})

    assert "SiteBucketName" in outputs
    assert "UploadsBucketName" in outputs
    assert "PresignEndpointForConfig" in outputs
    assert "ManageEndpointForConfig" in outputs


def test_use_existing_site_bucket_requires_bucket_name() -> None:
    app = cdk.App(context={"useExistingSiteBucket": "true"})
    with pytest.raises(ValueError, match="siteBucketName"):
        PhotoPickerAppStack(app, "MissingSiteBucketName")


def test_use_existing_uploads_bucket_requires_bucket_name() -> None:
    app = cdk.App(context={"useExistingUploadsBucket": "true"})
    with pytest.raises(ValueError, match="uploadsBucketName"):
        PhotoPickerAppStack(app, "MissingUploadsBucketName")


def test_manage_dns_requires_hosted_zone_name() -> None:
    app = cdk.App(context={"manageDns": "true"})
    with pytest.raises(ValueError, match="hostedZoneName"):
        PhotoPickerAppStack(
            app,
            "MissingHostedZone",
            domain_name="photos.example.com",
            certificate_arn="arn:aws:acm:us-east-1:123456789012:certificate/example",
        )


def test_manage_dns_requires_domain_name() -> None:
    app = cdk.App(context={"manageDns": "true"})
    with pytest.raises(ValueError, match="domainName"):
        PhotoPickerAppStack(
            app,
            "MissingDomainName",
            hosted_zone_name="example.com",
            certificate_arn="arn:aws:acm:us-east-1:123456789012:certificate/example",
        )


def test_manage_dns_requires_certificate() -> None:
    app = cdk.App(context={"manageDns": "true"})
    with pytest.raises(ValueError, match="certificateArn"):
        PhotoPickerAppStack(
            app,
            "MissingCertificate",
            domain_name="photos.example.com",
            hosted_zone_name="example.com",
        )


def test_manage_dns_requires_domain_to_match_zone() -> None:
    app = cdk.App(context={"manageDns": "true"})
    with pytest.raises(ValueError, match="subdomain"):
        PhotoPickerAppStack(
            app,
            "DomainMismatch",
            domain_name="photos.other-example.com",
            hosted_zone_name="example.com",
            certificate_arn="arn:aws:acm:us-east-1:123456789012:certificate/example",
        )


def test_domain_configuration_sets_alias_without_dns() -> None:
    _, template = synthesize_stack(
        domain_name="photos.example.com",
        certificate_arn="arn:aws:acm:us-east-1:123456789012:certificate/example",
    )

    template.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": {
                "Aliases": ["photos.example.com"],
            }
        },
    )
    template.resource_count_is("AWS::Route53::RecordSet", 0)
