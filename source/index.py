"""Stable handlers also used by the CloudFormation upload placeholders."""


def web(event, context):
    from lambda_function import lambda_handler
    return lambda_handler(event, context)


def collect(event, context):
    from collector import lambda_handler
    return lambda_handler(event, context)
