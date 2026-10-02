"""Web/API-only Lambda entry point for the v0.6.2 deployment package."""


def web(event, context):
    from lambda_function import lambda_handler
    return lambda_handler(event, context)
