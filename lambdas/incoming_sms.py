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
import urllib
from twilio.request_validator import *
from helper.dal import *
from helper.lambdautils import *
from helper.logger import get_logger

logger = get_logger(__name__)

database_name = os.getenv('DB_NAME')
db_cluster_name = os.getenv('DB_CLUSTER_NAME')
db_cluster_id = os.getenv('DB_CLUSTER_ID')
db_cluster_arn = os.getenv('DB_CLUSTER_ARN')
db_credentials_secrets_store_arn = os.getenv('DB_CRED_SECRETS_STORE_ARN')
twilio_auth = os.getenv('TWILIO_AUTH')
dal = DataAccessLayer(database_name, db_cluster_arn, db_credentials_secrets_store_arn)


def handler(event, context):
    request_valid = False
    if True: #u'twilioSignature' in event and u'Body' in event:
        print(event)
        parms = event['body']
        form_parameters = {}
        params = parms.split('&')
        for parm in params:
            oneparm = parm.split('=')
            form_parameters[oneparm[0]] = urllib.parse.unquote_plus(oneparm[1])
        print(form_parameters)
        validator = RequestValidator(twilio_auth)
        twil_sig = event['headers']['X-Twilio-Signature']
        print(twil_sig)
        domain = event['headers']['Host']
        path = event['requestContext']['path']
        print(domain+path)
        request_valid = validator.validate(
            domain+path,
            form_parameters,
            event['headers'][u'X-Twilio-Signature']
        )
    print(f'Validity check {request_valid}')
    to = form_parameters['To']
    to_tn=to[len(to)-10:len(to)]
    frm = form_parameters['From']
    from_tn=frm[len(frm)-10:len(frm)]
    msg=form_parameters['Body']
    success = dal.sms_incoming(to_tn, from_tn, msg)
    print(f'do incoming: {success}')
    if success<5:
        resp = f'Sorry, got error {success}'
    if success==5:
        resp = 'Got it'
    if success <= 5:
        response = {
            'statusCode': 200,
            'headers': { 'Content-Type': 'text/xml'},
            'body': f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{resp}</Message></Response>'
        }
    else:
        response = {
            'statusCode': 200
        }

    return(response)
