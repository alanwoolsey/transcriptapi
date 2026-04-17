import os

import boto3

from app.core.config import settings


def create_boto3_client(service_name: str):
    if settings.aws_shared_credentials_file:
        os.environ["AWS_SHARED_CREDENTIALS_FILE"] = settings.aws_shared_credentials_file
    if settings.aws_config_file:
        os.environ["AWS_CONFIG_FILE"] = settings.aws_config_file
    if settings.aws_profile:
        os.environ["AWS_PROFILE"] = settings.aws_profile
        session = boto3.session.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
        return session.client(service_name)
    return boto3.client(service_name, region_name=settings.aws_region)
