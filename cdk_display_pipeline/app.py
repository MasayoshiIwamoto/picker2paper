#!/usr/bin/env python3
import aws_cdk as cdk
import os
from display_pipeline.app_stack import DisplayPipelineStack


app = cdk.App()
DisplayPipelineStack(
    app,
    "DisplayPipelineStack",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION"),
    ),
)
app.synth()
