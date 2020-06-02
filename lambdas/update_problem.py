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
from helper.dal import *
from helper.lambdautils import *
from helper.logger import get_logger

logger = get_logger(__name__)

database_name = os.getenv('DB_NAME')
db_cluster_arn = os.getenv('DB_CLUSTER_ARN')
db_credentials_secrets_store_arn = os.getenv('DB_CRED_SECRETS_STORE_ARN')

dal = DataAccessLayer(database_name, db_cluster_arn, db_credentials_secrets_store_arn)

update_problem_valid_fields = ['problem_id', 'crew_type', 'strip', 'problem_type']

#-----------------------------------------------------------------------------------------------
# Input Validation
#-----------------------------------------------------------------------------------------------
def validate_update_problem_input_parameters(event):
    for field in update_problem_valid_fields:
        if field not in event:
            raise ValueError(f'Invalid update problem input parameter: {field}')


#-----------------------------------------------------------------------------------------------
# Lambda Entrypoint
#-----------------------------------------------------------------------------------------------
def handler(event, context):
    try:
        logger.info(f'Event received: {event}')
        if key_missing_or_empty_value(event, 'body'):
            raise ValueError('Invalid input - body missing')
        input_fields = json.loads(event['body'])
        validate_update_problem_input_parameters(input_fields)
        #validate user, get user_id
        data = json.dumps(event)
        y = json.loads(data)
        sub = y['requestContext']['authorizer']['claims']['sub']
        user_id,user_name,allowed_roles = dal.check_user(sub)
        if user_id == 0:
            return error(400, "no user found")
        #find crew for user in event
        event_id, mycrew_type = dal.get_event_and_crew(user_id)
        if event_id>0:
            problem_id = input_fields['problem_id']
            crew_type = input_fields['crew_type']
            strip = input_fields['strip']
            problem_type = input_fields['problem_type']
            works=dal.update_problem(user_id, problem_id, crew_type, strip, problem_type)
            if works:
                logger.debug(f'Updated Problem')
                return success({
                    'message': 'Problem updated'
                })
            else:
                return error(400, 'could not update problem')
        else:
            return(400, 'bad crew')
    except Exception as e:
        return handle_error(e)
