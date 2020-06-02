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

set_crew_valid_fields = ['event_id','push_token']

#-----------------------------------------------------------------------------------------------
# Input Validation
#-----------------------------------------------------------------------------------------------
def validate_set_crew_input_parameters(event):
    for field in set_crew_valid_fields:
        if field not in event:
            raise ValueError(f'Invalid hello input parameter: {field}')

#-----------------------------------------------------------------------------------------------
# Lambda Entrypoint
#-----------------------------------------------------------------------------------------------
def handler(event, context):
    try:
        #don't know why we need to encode/decode but..
        if key_missing_or_empty_value(event, 'body'):
            raise ValueError('Invalid input - body missing')
        input_fields = json.loads(event['body'])
        validate_set_crew_input_parameters(input_fields)
        event_id = input_fields['event_id']
        push_token = input_fields['push_token']
        data = json.dumps(event)
        y = json.loads(data)
        sub = y['requestContext']['authorizer']['claims']['sub']
        user_id,user_name,allowed_roles = dal.check_user(sub)
        if user_id == 0:
            return error(400, "no user found")
        possible_event_id, my_crew_type = dal.get_event_and_crew(user_id)
        print(f'event={event_id} possible={possible_event_id} user={user_id} mycrew={my_crew_type} allowed={allowed_roles}')
        if event_id == 0:
            event_id=2001
        crew_type=""
        if possible_event_id == 0: #no entry in crew table yet
            if event_id == 2001:
                crew_type = allowed_roles.split(',')[0] #use first allowed crew type
                print(f'test with allowed = {crew_type}')
                dal.add_crew(event_id, crew_type, user_id)
            else:
                if "REF" in allowed_roles:
                    print('assume ref')
                    crew_type="REF"
                    dal.add_crew(event_id, crew_type, user_id)
                else:
                    print('not ref, no crew')
                    crew_type = ""
        else:
            if event_id == possible_event_id: #aleady in a crew for selected event
                print('match or test')
                crew_type = my_crew_type
            else:
                event_id=2001
                crew_type=allowed_roles.split(',')[0]
                print('Forced Test')
                dal.add_crew(event_id, crew_type, user_id)
        if crew_type != "":
            return success({
                'crew_type': crew_type,
                'topic': crew_type+str(event_id)
            })
        else:
            return error(400, 'bad crew for event')
    except Exception as e:
        return handle_error(e)
