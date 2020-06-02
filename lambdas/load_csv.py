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
import boto3
import csv
from helper.dal import *
from helper.lambdautils import *
from helper.logger import get_logger

logger = get_logger(__name__)

database_name = os.getenv('DB_NAME')
db_cluster_arn = os.getenv('DB_CLUSTER_ARN')
db_credentials_secrets_store_arn = os.getenv('DB_CRED_SECRETS_STORE_ARN')

dal = DataAccessLayer(database_name, db_cluster_arn, db_credentials_secrets_store_arn)

def handler(event, context):
    print("starting")
    region='us-east-1'
    recList=[]
    try:
        s3=boto3.client('s3')
        confile= s3.get_object(Bucket='stripcall-email', Key='hirelist.csv')
        recList = confile['Body'].read().decode('utf-8').splitlines(True)
        firstrecord=True
        csv_reader = csv.reader(recList, delimiter=',', quotechar='"')
        print("Got csv reader")
        firstfew=0;
        for row in csv_reader:
            if (firstrecord):
                firstrecord=False
                continue
            if (firstfew<10):
                print(row)
            if len(row)>13:
                if len(row[5])>0:
                    email = row[13]
                    lastfirst = row[5].split(',')
                    firstname = lastfirst[1].replace(' ','')
                    lastname=lastfirst[0]
                    full_name = firstname + " " + lastname
                    user_name = firstname + lastname[0]
                    if (firstfew<10): print(f'email={email}, fullname={full_name}, username={user_name}')
                    dal.insert_email(email, full_name, user_name, "ARM")
                    firstfew+=1
        print('Armory Put succeeded:')
        confile= s3.get_object(Bucket='stripcall-email', Key='reflist.csv')
        recList = confile['Body'].read().decode('utf-8').splitlines(True)
        firstrecord=True
        csv_reader = csv.reader(recList, delimiter=',', quotechar='"')
        print("Got ref csv reader")
        firstfew=0;
        for row in csv_reader:
            if (firstrecord):
                firstrecord=False
                continue
            if (firstfew<10):
                print(row)
            if len(row)>2:
                if len(row[0])>0:
                    email = row[2]
                    lastname = row[0]
                    firstname = row[1]
                    full_name = firstname + " " + lastname
                    user_name = firstname[0] + lastname
                    if (firstfew<10): print(f'email={email}, fullname={full_name}, username={user_name}')
                    dal.insert_email(email, full_name, user_name, "REF")
                    firstfew+=1
        print('Ref Put succeeded:')
    except Exception as e:
        return handle_error(e)
