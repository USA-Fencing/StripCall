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


def handler(event, context):

    try:
        code = 1
        loops = 0
        while code == 1:
            code, error_code, msg = dal.pokeme()
            if loops > 40:  #about 3 seconds per iteration, 20 per minute
                break
            loops+=1
        if code==2:
            active_tournaments = dal.tourney()
            for record in active_tournaments:
                if record['state']==0: #event not initialized
                    event_id = record['event_id']
                    print(f'Starting Tournament {event_id}')
                    works=dal.create_problem(1001, event_id, "ARM", "Genrl", '00')
                    if not works:
                        return error(400, "Could not create problem")
                    works=dal.change_state(event_id, 1) #active
                    if not works:
                        return error(400, "Could not change state")
            oldies = dal.old_events()
            for record in oldies:
                if record['state']==1: #active
                    event_id=record['event_id']
                    print(f'Ending Tournament {event_id}')
                    dal.cleanup(event_id)
                    works = dal.change_state(event_id, 2) #finished
                    if not works:
                        return error(400, "Could not create problem")
            # Create CloudWatchEvents client
            cloudwatch_events=boto3.client('events')
            response = cloudwatch_events.list_rules()
            for rule in response["Rules"]:
                name = rule["Name"]
                if name.find("KeepAlive")>0:
            # Put an event rule
                    if len(active_tournaments)>0:
                        response=cloudwatch_events.enable_rule(Name=name)
                    else:
                        response=cloudwatch_events.disable_rule(Name=name)
                    print(f'response={response}')
            return success({
                'message': 'woke'
            })
        else:
            return error(400, "Could not wake database")
    except Exception as e:
        return handle_error(e)
