import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from display_pipeline.app_stack import DisplayPipelineStack


def synthesize_stack(context: dict | None = None) -> tuple[DisplayPipelineStack, Template]:
    app = cdk.App(context=context or {})
    stack = DisplayPipelineStack(app, "DisplayPipelineStack")
    template = Template.from_stack(stack)
    return stack, template


def test_stack_synthesizes_and_has_key_resources() -> None:
    stack, template = synthesize_stack()

    # Validate key resource counts
    template.resource_count_is("AWS::S3::Bucket", 1)
    template.resource_count_is("AWS::Lambda::Function", 3)
    template.resource_count_is("AWS::ApiGateway::RestApi", 1)

    # Spot check Lambda environment configuration
    functions = template.find_resources("AWS::Lambda::Function")
    handler_runtimes = {props["Properties"]["Handler"]: props["Properties"]["Runtime"] for props in functions.values()}
    assert handler_runtimes["handler.handler"] == "python3.11"

    # Ensure synth produces deployable assembly (approx. `cdk synth`)
    assembly = stack.node.root.synth()
    artifact = assembly.get_stack_by_name("DisplayPipelineStack")
    assert isinstance(artifact.template, dict)


def test_manage_dns_requires_hosted_zone() -> None:
    app = cdk.App(
        context={
            "manageDns": "true",
            "nextImageDomainName": "display.example.com",
        }
    )
    with pytest.raises(ValueError, match="requires hostedZoneName"):
        DisplayPipelineStack(app, "DnsValidationStack")


def test_manage_dns_requires_domain_to_match_zone() -> None:
    app = cdk.App(
        context={
            "manageDns": "true",
            "hostedZoneName": "example.com",
            "nextImageDomainName": "other-domain.com",
        }
    )
    with pytest.raises(ValueError, match="subdomain"):
        DisplayPipelineStack(app, "DnsMismatchStack")


def test_domain_resources_created_when_certificate_provided() -> None:
    _, template = synthesize_stack(
        {
            "nextImageDomainName": "display.example.com",
            "nextImageCertificateArn": "arn:aws:acm:ap-northeast-1:123456789012:certificate/example",
            "nextImageTruststoreUri": "s3://example-bucket/myCA.pem",
            "nextImageStageName": "prod",
        }
    )

    template.has_resource_properties(
        "AWS::ApiGateway::DomainName",
        {
            "DomainName": "display.example.com",
            "RegionalCertificateArn": "arn:aws:acm:ap-northeast-1:123456789012:certificate/example",
        },
    )

    # No DNS record should be created when manageDns is false
    assert template.resource_count_is("AWS::Route53::RecordSet", 0) is None


def test_diff_between_identical_templates_is_empty() -> None:
    _, template_a = synthesize_stack()
    _, template_b = synthesize_stack()
    assert template_a.to_json() == template_b.to_json()
