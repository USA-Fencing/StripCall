#called once a day at midnight
"""
  Copyright 2020 Brian Rosen, All Rights Reserved.
  Brian Rosen Licensing Statement:
  Contact Author for license

  Derived from work Copyright 2019 Amazon.com, Inc. or its affiliates. All Rights Reserved.

  Amazon Licensing statement:

  Permission is hereby granted, free of charge, to any person obtaining a copy of this
  software and associated documentation files (the "Software"), to deal in the Software
  without restriction, including without limitation the rights to use, copy, modify,
  merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
  permit persons to whom the Software is furnished to do so.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
  INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
  PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
  HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
  OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
  SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""
import json
import os
import boto3
from helper.dal import *
from helper.lambdautils import *
from helper.logger import get_logger

logger = get_logger(__name__)

database_name = os.getenv('DB_NAME')
db_cluster_name = os.getenv('DB_CLUSTER_NAME')
db_cluster_id = os.getenv('DB_CLUSTER_ID')
db_cluster_arn = os.getenv('DB_CLUSTER_ARN')
db_credentials_secrets_store_arn = os.getenv('DB_CRED_SECRETS_STORE_ARN')
dal = DataAccessLayer(database_name, db_cluster_arn, db_credentials_secrets_store_arn)

check_email_valid_fields = ['auth_code', 'email']

#-----------------------------------------------------------------------------------------------
# Input Validation
#-----------------------------------------------------------------------------------------------
def validate_check_email_input_parameters(event):
    for field in check_email_valid_fields:
        if field not in event:
            raise ValueError(f'Invalid message input parameter: {field}')

#-----------------------------------------------------------------------------------------------
# Lambda Entrypoint
#-----------------------------------------------------------------------------------------------
def handler(event, context):
    try:
        logger.info(f'Event received: {event}')
        if key_missing_or_empty_value(event, 'body'):
            raise ValueError('Invalid input - body missing')
        input_fields = json.loads(event['body'])
        validate_check_email_input_parameters(input_fields)
        data = json.dumps(event)
        code, err, msg = dal.pokeme()
        print(f'code={code}')
        if code == 0:
            return error(400, "wake db failed")
        elif code == 1:
            return success({'Success' : 0})
        auth_code = input_fields['auth_code']
        email = input_fields['email']
        if auth_code != "3cb6a0a2-deac-47a9-bb60-1d8d6d3386dc":
            return error(401, 'Not Authorized')
        good=dal.check_email(email)
        if good:
            print('success')
            return success({'Success' : 1,})
        else:
            print('failure')
            return success({'Bad Email' : 0,})
    except Exception as e:
        return handle_error(e)
