from pathlib import Path
from typing import Optional
import typing
import aws_cdk as cdk
from constructs import Construct
from aws_cdk import (
    Duration,
    RemovalPolicy,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_certificatemanager as acm,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_iam as iam,
    aws_s3_deployment as s3deploy,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
LAMBDA_DIR = PACKAGE_ROOT / "lambda"
SITE_DIR = PACKAGE_ROOT / "site"


class PhotoPickerAppStack(cdk.Stack):
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

        use_existing_site_bucket = bool(self.node.try_get_context("useExistingSiteBucket"))
        use_existing_uploads_bucket = bool(self.node.try_get_context("useExistingUploadsBucket"))

        if use_existing_site_bucket:
            if not site_bucket_name:
                raise ValueError("useExistingSiteBucket=true の場合は siteBucketName を指定してください。")
            site_bucket = s3.Bucket.from_bucket_name(
                self,
                "SiteBucketImported",
                site_bucket_name,
            )
        else:
            site_bucket = s3.Bucket(
                self,
                "SiteBucket",
                bucket_name=site_bucket_name,
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                encryption=s3.BucketEncryption.S3_MANAGED,
                removal_policy=RemovalPolicy.RETAIN,
                auto_delete_objects=False,
            )

        if use_existing_uploads_bucket:
            if not uploads_bucket_name:
                raise ValueError("useExistingUploadsBucket=true の場合は uploadsBucketName を指定してください。")
            uploads_bucket = s3.Bucket.from_bucket_name(
                self,
                "UploadsBucketImported",
                uploads_bucket_name,
            )
        else:
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
                        max_age=3000,
                    )
                ],
            )

        cf_cert = None
        if certificate_arn:
            cf_cert = acm.Certificate.from_certificate_arn(
                self, "ImportedCert", certificate_arn
            )

        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
            certificate=cf_cert,
            domain_names=[domain_name] if domain_name and cf_cert else None,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
        )

        oac = cloudfront.CfnOriginAccessControl(
            self,
            "S3OAC",
            origin_access_control_config=cloudfront.CfnOriginAccessControl.OriginAccessControlConfigProperty(
                name=f"{self.stack_name}-s3-oac",
                origin_access_control_origin_type="s3",
                signing_behavior="always",
                signing_protocol="sigv4",
            ),
        )

        cfn_dist = typing.cast(cloudfront.CfnDistribution, distribution.node.default_child)
        cfn_dist.add_property_override(
            "DistributionConfig.Origins.0.OriginAccessControlId", oac.attr_id
        )

        site_bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowCloudFrontAccessViaOAC",
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("cloudfront.amazonaws.com")],
                actions=["s3:GetObject"],
                resources=[site_bucket.arn_for_objects("*")],
                conditions={
                    "StringEquals": {
                        "AWS:SourceArn": f"arn:aws:cloudfront::{cdk.Aws.ACCOUNT_ID}:distribution/{distribution.distribution_id}"
                    }
                },
            )
        )

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
        normalized_zone = hosted_zone_name.rstrip(".").lower() if hosted_zone_name else None
        normalized_domain = domain_name.rstrip(".").lower() if domain_name else None

        if manage_dns:
            if not hosted_zone_name:
                raise ValueError("manageDns=true requires hostedZoneName to be set.")
            if not domain_name:
                raise ValueError("manageDns=true requires domainName to be set.")
            if not cf_cert:
                raise ValueError("manageDns=true requires certificateArn to be set.")
            if not normalized_domain:
                raise ValueError("domainName must not be empty.")
            if not normalized_zone:
                raise ValueError("hostedZoneName must not be empty.")
            if normalized_domain != normalized_zone and not normalized_domain.endswith(f".{normalized_zone}"):
                raise ValueError(
                    "When manageDns=true, domainName must equal hostedZoneName or be a subdomain of it."
                )

        if manage_dns and domain_name and hosted_zone_name and cf_cert:
            lookup_zone_name = hosted_zone_name.rstrip(".")
            zone = route53.HostedZone.from_lookup(
                self, "HostedZone", domain_name=lookup_zone_name
            )
            record_name = domain_name.rstrip(".")
            zone_suffix = lookup_zone_name.lower()
            if record_name.lower().endswith("." + zone_suffix):
                record_name = record_name[: -(len(zone_suffix) + 1)]
            elif record_name.lower() == zone_suffix:
                record_name = "@"
            route53.ARecord(
                self,
                "AliasRecord",
                zone=zone,
                record_name=record_name,
                target=route53.RecordTarget.from_alias(
                    targets.CloudFrontTarget(distribution)
                ),
            )
        elif domain_name and cf_cert:
            cdk.CfnOutput(
                self,
                "SiteDnsRecord",
                value=(
                    "Create an alias A record for "
                    f"{domain_name} to {distribution.distribution_domain_name} "
                    "(hosted zone ID Z2FDTNDATAQYW2)"
                ),
            )

        cors_origin = f"https://{domain_name}" if domain_name else "*"
        uploads_prefix = self.node.try_get_context("uploadsPrefix") or "uploads/"
        processed_prefix = self.node.try_get_context("processedPrefix") or "processed/"

        presign_fn = _lambda.Function(
            self,
            "PresignFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=_lambda.Code.from_asset(str(LAMBDA_DIR / "presign")),
            timeout=Duration.seconds(10),
            environment={
                "UPLOAD_BUCKET": uploads_bucket.bucket_name,
                "ALLOW_ORIGIN": cors_origin,
                "GOOGLE_CLIENT_ID": self.node.try_get_context("googleClientId") or "",
                "ALLOWED_EMAIL_DOMAINS": self.node.try_get_context("allowedEmailDomains") or "",
                "ALLOWED_EMAILS": self.node.try_get_context("allowedEmails") or "",
            },
        )
        uploads_bucket.grant_put(presign_fn)

        manage_fn = _lambda.Function(
            self,
            "ManageUploadsFunction",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.handler",
            code=_lambda.Code.from_asset(str(LAMBDA_DIR / "manage_uploads")),
            timeout=Duration.seconds(20),
            environment={
                "UPLOAD_BUCKET": uploads_bucket.bucket_name,
                "ALLOW_ORIGIN": cors_origin,
                "GOOGLE_CLIENT_ID": self.node.try_get_context("googleClientId") or "",
                "ALLOWED_EMAIL_DOMAINS": self.node.try_get_context("allowedEmailDomains") or "",
                "ALLOWED_EMAILS": self.node.try_get_context("allowedEmails") or "",
                "UPLOAD_PREFIX": uploads_prefix,
                "PROCESSED_PREFIX": processed_prefix,
            },
        )
        uploads_bucket.grant_read_write(manage_fn)

        allow_origins = ([cors_origin] if cors_origin != "*" else apigw.Cors.ALL_ORIGINS)
        api = apigw.RestApi(
            self,
            "PresignApi",
            rest_api_name="PhotoPicker Presign API",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=allow_origins,
                allow_methods=["OPTIONS", "POST", "GET", "DELETE"],
                allow_headers=["content-type", "authorization", "x-device-token"],
            ),
            deploy_options=apigw.StageOptions(
                throttling_rate_limit=50,
                throttling_burst_limit=100,
            ),
        )

        presign_res = api.root.add_resource("presign")
        presign_res.add_method(
            "POST",
            apigw.LambdaIntegration(presign_fn, proxy=True),
            method_responses=[apigw.MethodResponse(status_code="200")],
        )

        uploads_res = api.root.add_resource("uploads")
        uploads_integration = apigw.LambdaIntegration(manage_fn, proxy=True)
        uploads_res.add_method(
            "GET",
            uploads_integration,
            method_responses=[apigw.MethodResponse(status_code="200")],
        )
        uploads_res.add_method(
            "DELETE",
            uploads_integration,
            method_responses=[apigw.MethodResponse(status_code="200")],
        )

        presign_endpoint_url = f"{api.url}presign"
        manage_endpoint_url = f"{api.url}uploads"
        cdk.CfnOutput(self, "SiteBucketName", value=site_bucket.bucket_name)
        cdk.CfnOutput(self, "UploadsBucketName", value=uploads_bucket.bucket_name)
        cdk.CfnOutput(self, "DistributionDomainName", value=distribution.distribution_domain_name)
        cdk.CfnOutput(
            self,
            "PresignEndpointForConfig",
            value=presign_endpoint_url,
            description="Use this value for site/config.js upload.presignEndpoint.",
        )
        cdk.CfnOutput(
            self,
            "ManageEndpointForConfig",
            value=manage_endpoint_url,
            description="Use this value for site/config.js upload.manageEndpoint.",
        )

        s3deploy.BucketDeployment(
            self,
            "DeploySite",
            sources=[s3deploy.Source.asset(str(SITE_DIR))],
            destination_bucket=site_bucket,
            exclude=["cdk/*", "cdk/**", "tools/*", "tools/**", "*.example.js"],
            distribution=distribution,
            distribution_paths=["/*"],
            cache_control=[s3deploy.CacheControl.from_string("public, max-age=300")],
        )
