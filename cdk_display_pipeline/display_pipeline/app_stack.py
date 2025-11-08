from typing import Optional
import typing
import aws_cdk as cdk
from constructs import Construct
from aws_cdk import (
    Duration,
    RemovalPolicy,
    aws_s3 as s3,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_route53 as route53,
    aws_s3_notifications as s3n,
)


class DisplayPipelineStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        domain_name: Optional[str] = None,
        hosted_zone_name: Optional[str] = None,
        site_bucket_name: Optional[str] = None,
        uploads_bucket_name: Optional[str] = None,
        certificate_arn: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        uploads_bucket = s3.Bucket(
            self,
            "UploadsBucket",
            bucket_name=uploads_bucket_name,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.POST],
                    allowed_origins=(
                        [f"https://{domain_name}"] if domain_name else ["*"]
                    ),
                    allowed_headers=["*"],
                    exposed_headers=["ETag"],
                    max_age=3000,  # seconds (int)
                )
            ],
        )

        processed_bucket = uploads_bucket

        def _context_flag(*keys: str) -> typing.Optional[bool]:
            for key in keys:
                ctx = self.node.try_get_context(key)
                if isinstance(ctx, str):
                    return ctx.lower() in ("1", "true", "yes")
                if isinstance(ctx, bool):
                    return ctx
            return None

        manage_dns = _context_flag("manageDns", "enableDns")
        if manage_dns is None:
            disable_dns_ctx = _context_flag("disableDns")
            if disable_dns_ctx is not None:
                manage_dns = not disable_dns_ctx
            else:
                manage_dns = False

        hosted_zone_name = hosted_zone_name or self.node.try_get_context("hostedZoneName")
        uploads_prefix = self.node.try_get_context("uploadsPrefix") or "uploads/"
        processed_prefix = self.node.try_get_context("processedPrefix") or "processed/"
        epaper_width = str(self.node.try_get_context("epaperWidth") or "800")
        epaper_height = str(self.node.try_get_context("epaperHeight") or "480")
        epaper_rotate = str(self.node.try_get_context("epaperRotate") or "0")
        epaper_saturation = str(self.node.try_get_context("epaperSaturation") or "1.2")
        epaper_brightness = str(self.node.try_get_context("epaperBrightness") or "1.0")
        state_key = self.node.try_get_context("displayStateKey") or "state/.display_state.json"
        presigned_ttl = str(self.node.try_get_context("presignedTtlSeconds") or "120")
        next_image_domain_name = self.node.try_get_context("nextImageDomainName") or None
        next_image_certificate_arn = self.node.try_get_context("nextImageCertificateArn") or None
        next_image_truststore_uri = self.node.try_get_context("nextImageTruststoreUri") or None
        next_image_stage_name = self.node.try_get_context("nextImageStageName") or "prod"

        normalized_zone = hosted_zone_name.rstrip(".").lower() if hosted_zone_name else None
        normalized_domain = next_image_domain_name.rstrip(".").lower() if next_image_domain_name else None

        if manage_dns:
            if not hosted_zone_name:
                raise ValueError("manageDns=true requires hostedZoneName to be set.")
            if not next_image_domain_name:
                raise ValueError("manageDns=true requires nextImageDomainName to be set.")
            if not normalized_domain:
                raise ValueError("nextImageDomainName must not be empty.")
            if not normalized_zone:
                raise ValueError("hostedZoneName must not be empty.")
            if normalized_domain != normalized_zone and not normalized_domain.endswith(f".{normalized_zone}"):
                raise ValueError(
                    "When manageDns=true, nextImageDomainName must equal hostedZoneName or be a subdomain of it."
                )

        next_image_fn = _lambda.Function(
            self,
            "NextImageFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=_lambda.Code.from_asset("lambda/get_next_image"),
            timeout=Duration.seconds(20),
            environment={
                "ASSETS_BUCKET": uploads_bucket.bucket_name,
                "PROCESSED_PREFIX": processed_prefix,
                "STATE_KEY": state_key,
                "URL_TTL_SECONDS": presigned_ttl,
            },
        )
        uploads_bucket.grant_read_write(next_image_fn)

        # Lambda for image formatting
        format_fn = _lambda.Function(
            self,
            "FormatImageFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=_lambda.Code.from_asset(
                "lambda/format_image",
                bundling=cdk.BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -R . /asset-output",
                    ],
                ),
            ),
            timeout=Duration.seconds(60),
            memory_size=512,
            environment={
                "DEST_BUCKET": processed_bucket.bucket_name,
                "TARGET_WIDTH": epaper_width,
                "TARGET_HEIGHT": epaper_height,
                "PROCESSED_PREFIX": processed_prefix,
                "ROTATE": epaper_rotate,
                "SATURATION": epaper_saturation,
                "BRIGHTNESS": epaper_brightness,
            },
        )

        uploads_bucket.grant_read(format_fn)
        processed_bucket.grant_put(format_fn)

        uploads_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(format_fn),
            s3.NotificationKeyFilter(prefix=uploads_prefix)
        )

        # API Gateway
        next_image_api = apigw.RestApi(
            self,
            "NextImageApi",
            rest_api_name="Display Pipeline Next Image API",
            endpoint_types=[apigw.EndpointType.REGIONAL],
            disable_execute_api_endpoint=True,
            deploy_options=apigw.StageOptions(stage_name=next_image_stage_name),
        )

        next_image_resource = next_image_api.root.add_resource("next-image")
        next_image_resource.add_method(
            "GET",
            apigw.LambdaIntegration(next_image_fn, proxy=True),
            method_responses=[apigw.MethodResponse(status_code="200")],
        )

        next_image_domain = None
        if next_image_domain_name and next_image_certificate_arn:
            endpoint_conf = apigw.CfnDomainName.EndpointConfigurationProperty(
                types=["REGIONAL"],
            )
            mtls_property = None
            if next_image_truststore_uri:
                mtls_property = apigw.CfnDomainName.MutualTlsAuthenticationProperty(
                    truststore_uri=next_image_truststore_uri
                )
            next_image_domain = apigw.CfnDomainName(
                self,
                "NextImageDomain",
                domain_name=next_image_domain_name,
                regional_certificate_arn=next_image_certificate_arn,
                security_policy="TLS_1_2",
                endpoint_configuration=endpoint_conf,
                mutual_tls_authentication=mtls_property,
            )

            base_path_mapping = apigw.CfnBasePathMapping(
                self,
                "NextImageBasePathMapping",
                domain_name=next_image_domain.ref,
                rest_api_id=next_image_api.rest_api_id,
                stage=next_image_api.deployment_stage.stage_name,
                base_path="",
            )
            base_path_mapping.node.add_dependency(next_image_api.deployment_stage)

            if hosted_zone_name and manage_dns:
                next_zone = route53.HostedZone.from_lookup(
                    self, "NextImageHostedZone", domain_name=hosted_zone_name
                )
                record_name = next_image_domain_name
                if record_name.endswith("." + hosted_zone_name):
                    record_name = record_name[: -(len(hosted_zone_name) + 1)]
                elif record_name == hosted_zone_name:
                    record_name = "@"

                route53.CfnRecordSet(
                    self,
                    "NextImageAliasRecord",
                    hosted_zone_id=next_zone.hosted_zone_id,
                    name=next_image_domain_name,
                    type="A",
                    alias_target=route53.CfnRecordSet.AliasTargetProperty(
                        dns_name=next_image_domain.attr_regional_domain_name,
                        hosted_zone_id=next_image_domain.attr_regional_hosted_zone_id,
                        evaluate_target_health=False,
                    ),
                )
            elif next_image_domain_name:
                dns_target = (
                    f"{next_image_domain.attr_regional_domain_name} "
                    f"(hosted zone ID {next_image_domain.attr_regional_hosted_zone_id})"
                )
                cdk.CfnOutput(
                    self,
                    "NextImageManualDnsRecord",
                    value=f"A {next_image_domain_name} -> {dns_target}",
                    description="Create this alias A record if you manage DNS manually.",
                )

        # Outputs
        cdk.CfnOutput(
            self,
            "ManualUploadBucketName",
            value=uploads_bucket.bucket_name,
            description=f"S3 bucket for manual uploads (prefix: {uploads_prefix})",
        )
        cdk.CfnOutput(
            self,
            "ProcessedBucketName",
            value=processed_bucket.bucket_name,
            description=f"S3 bucket where converted images are stored (prefix: {processed_prefix})",
        )

        if next_image_domain_name and next_image_certificate_arn:
            cdk.CfnOutput(
                self,
                "NextImageMtlsEndpoint",
                value=f"https://{next_image_domain_name}/next-image",
                description="Invoke this endpoint with client certificates for mTLS.",
            )
