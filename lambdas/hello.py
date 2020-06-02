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

import os
import json
from helper.dal import *
from helper.lambdautils import *
from helper.logger import get_logger

logger = get_logger(__name__)

database_name = os.getenv('DB_NAME')
db_cluster_arn = os.getenv('DB_CLUSTER_ARN')
db_credentials_secrets_store_arn = os.getenv('DB_CRED_SECRETS_STORE_ARN')

dal = DataAccessLayer(database_name, db_cluster_arn, db_credentials_secrets_store_arn)

hello_valid_fields = ['crew_type']

#-----------------------------------------------------------------------------------------------
# Input Validation
#-----------------------------------------------------------------------------------------------
def validate_hello_input_parameters(event):
    for field in hello_valid_fields:
        if field not in event:
            raise ValueError(f'Invalid hello input parameter: {field}')

#-----------------------------------------------------------------------------------------------
# Lambda Entrypoint
#-----------------------------------------------------------------------------------------------
def handler(event, context):
    try:
        logger.info(f'Event received: {event}')
        code, error, msg = dal.pokeme()
        if code == 0:
            return error(400, "wake db failed")
        elif code == 1:
            return success({
            'Success' : 0,
            'UserId' : 1001,
            'UserName': 'user',
            'Crew' : 'REF',
            'Tournaments' : []
            })
        print("woke")
        data = json.dumps(event)
        y = json.loads(data)
        sub = y['requestContext']['authorizer']['claims']['sub']
        user_id,user_name,allowed_roles = dal.check_user(sub)
        print(f'user_id={user_id} user_name={user_name}')
        if user_id == 0:
            print("no user found")
            return error(400, "no user found")
        tournaments = dal.tourney()
        return success({
            'Success' : 1,
            'UserId' : user_id,
            'UserName': user_name,
            'Crew': allowed_roles,
            'Tournaments': tournaments
        })
    except Exception as e:
        return handle_error(e)
