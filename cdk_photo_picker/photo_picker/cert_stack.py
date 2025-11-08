from typing import Optional
import aws_cdk as cdk
from constructs import Construct
from aws_cdk import (
    aws_certificatemanager as acm,
    aws_route53 as route53,
)


class PhotoPickerCertStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        domain_name: str,
        hosted_zone_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        zone = route53.HostedZone.from_lookup(
            self, "HostedZone", domain_name=hosted_zone_name
        )

        cert = acm.DnsValidatedCertificate(
            self,
            "Certificate",
            domain_name=domain_name,
            hosted_zone=zone,
            region="us-east-1",
        )

        self.certificate_arn = cert.certificate_arn

        cdk.CfnOutput(self, "CertificateArn", value=self.certificate_arn)
