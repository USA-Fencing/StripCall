"""
  Copyright 2019 Brian Rosen.  All rights reserved.

  Adapted from works Copyright 2019 Amazon.com, Inc. or its affiliates.
"""
import json
import os
import boto3
import base64
from urllib import request, parse
import requests
from .logger import get_logger
from aws_xray_sdk.core import xray_recorder, patch_all
logger = get_logger(__name__)

is_lambda_environment = (os.getenv('AWS_LAMBDA_FUNCTION_NAME') is not None)

# AWS X-Ray support

if is_lambda_environment:
    patch_all()

users_table_name = os.getenv('USERS_TABLE_NAME', 'users')
events_table_name = os.getenv('EVENTS_TABLE_NAME', 'events')
crews_table_name = os.getenv('CREWS_TABLE_NAME', 'crews')
problems_table_name = os.getenv('PROBLEMS_TABLE_NAME', 'problems')
messages_table_name = os.getenv('MESSAGES_TABLE_NAME', 'messages')
receipts_table_name = os.getenv('RECEIPTS_TABLE_NAME', 'receipts')
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH")
FCM_KEY = os.getenv("FCM_KEY")


class DataAccessLayerException(Exception):

    def __init__(self, original_exception):
        self.original_exception = original_exception

class DataAccessLayer:

    def __init__(self, database_name, db_cluster_arn, db_credentials_secrets_store_arn):
        self._rdsdata_client = boto3.client('rds-data')
        self._database_name = database_name
        self._db_cluster_arn = db_cluster_arn
        self._db_credentials_secrets_store_arn = db_credentials_secrets_store_arn

    @staticmethod
    def _xray_start(segment_name):
        if is_lambda_environment and xray_recorder:
            xray_recorder.begin_subsegment(segment_name)

    @staticmethod
    def _xray_stop():
        if is_lambda_environment and xray_recorder:
            xray_recorder.end_subsegment()

    @staticmethod
    def _xray_add_metadata(name, value):
        if is_lambda_environment and xray_recorder and xray_recorder.current_subsegment():
            return xray_recorder.current_subsegment().put_metadata(name, value)

    def execute_statement(self, sql_stmt, sql_params=[], transaction_id=None):
        parameters = f' with parameters: {sql_params}' if len(sql_params) > 0 else ''
        logger.debug(f'Running SQL statement: {sql_stmt}{parameters}')
        DataAccessLayer._xray_start('execute_statement')
        try:
            DataAccessLayer._xray_add_metadata('sql_statement', sql_stmt)
            parameters = {
                'secretArn': self._db_credentials_secrets_store_arn,
                'database': self._database_name,
                'resourceArn': self._db_cluster_arn,
                'sql': sql_stmt,
                'parameters': sql_params
            }
            if transaction_id is not None:
                parameters['transactionId'] = transaction_id
            result = self._rdsdata_client.execute_statement(**parameters)
        except Exception as e:
            logger.debug(f'Error running SQL statement (error class: {e.__class__})')
            raise DataAccessLayerException(e) from e
        else:
            DataAccessLayer._xray_add_metadata('rdsdata_executesql_result', json.dumps(result))
            return result
        finally:
           DataAccessLayer._xray_stop()

    def batch_execute_statement(self, sql_stmt, sql_param_sets, batch_size, transaction_id=None):
        parameters = f' with parameters: {sql_param_sets}' if len(sql_param_sets) > 0 else ''
        logger.debug(f'Running SQL statement: {sql_stmt}{parameters}')
        DataAccessLayer._xray_start('batch_execute_statement')
        try:
            array_length = len(sql_param_sets)
            num_batches = 1 + len(sql_param_sets)//batch_size
            results = []
            for i in range(0, num_batches):
                start_idx = i*batch_size
                end_idx = min(start_idx + batch_size, array_length)
                batch_sql_param_sets = sql_param_sets[start_idx:end_idx]
                if len(batch_sql_param_sets) > 0:
                    print(f'Running SQL statement: [batch #{i+1}/{num_batches}, batch size {batch_size}, SQL: {sql_stmt}]')
                    DataAccessLayer._xray_add_metadata('sql_statement', sql_stmt)
                    parameters = {
                        'secretArn': self._db_credentials_secrets_store_arn,
                        'database': self._database_name,
                        'resourceArn': self._db_cluster_arn,
                        'sql': sql_stmt,
                        'parameterSets': batch_sql_param_sets
                    }
                    if transaction_id is not None:
                        parameters['transactionId'] = transaction_id
                    result = self._rdsdata_client.batch_execute_statement(**parameters)
                    results.append(result)
        except Exception as e:
            logger.debug(f'Error running SQL statement (error class: {e.__class__})')
            raise DataAccessLayerException(e) from e
        else:
            DataAccessLayer._xray_add_metadata('rdsdata_executesql_result', json.dumps(result))
            print(json.dumps(result))
            return results
        finally:
           DataAccessLayer._xray_stop()

    #-----------------------------------------------------------------------------------------------
    # Package Functions
    #-----------------------------------------------------------------------------------------------
    def pokeme(self):
        parameters = {
            'secretArn': self._db_credentials_secrets_store_arn,
            'database': self._database_name,
            'resourceArn': self._db_cluster_arn,
            'sql': 'SELECT event_id FROM events WHERE start_date_utc>now()'
        }
        try:
            result = self._rdsdata_client.execute_statement(**parameters)
            print('success')
            return 2, 200, 'success'
        except Exception as e:
            if 'Communications link failure' in str(e):
                print('retry')
                return 1, 400, f'Timeout Error: {e}'
            else:
                print(f'pokeme error e={e}')
                return 0, 400, f'Wakeup Error: {e}'

    def check_user(self,sub):
        DataAccessLayer._xray_start('check_user')
        try:
            sql_parameters = [
                {'name':'sub', 'value':{'stringValue': sub}}
            ]
            sql = f'select user_id, user_name, allowed_roles' \
                f' from {users_table_name}' \
                f' where sub = :sub'
            response = self.execute_statement(sql, sql_parameters)
            returned_records = response['records']
            print(returned_records)
            if len(returned_records) == 1:
                return returned_records[0][0]['longValue'], returned_records[0][1]['stringValue'], returned_records[0][2]['stringValue']
            else:
                return 0,"",""
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def get_event_and_crew(self, user_id):
        DataAccessLayer._xray_start('get_event_and_crew')
        try:
            sql_parameters = [
                {'name':'user_id', 'value':{'longValue': user_id}},
            ]
            sql = f'select crews.event_id, crews.crew_type' \
                f' from {crews_table_name}' \
                f' inner join events on crews.event_id = events.event_id' \
                f' where crews.user_id=:user_id' \
                f' and events.state=1'
            response = self.execute_statement(sql, sql_parameters)
            returned_records = response['records']
            if len(returned_records) == 1:
                event_id = returned_records[0][0]['longValue']
                if event_id>0:
                    return event_id, returned_records[0][1]['stringValue']
            sql = f'select crew_type from {crews_table_name} ' \
                f'where event_id = 2001 and user_id = :user_id '
            response = self.execute_statement(sql, sql_parameters)
            returned_records = response['records']
            if len(returned_records) == 1:
                return 2001, returned_records[0][0]['stringValue']
            else:
                return 0,""
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def get_problem(self, problem_id):
        DataAccessLayer._xray_start('get_problem')
        try:
            sql_parameters = [
                {'name':'problem_id', 'value':{'longValue': problem_id}},
            ]
            sql = f'select event_id, crew_type, strip, problem_type, reporter_id' \
                f' from {problems_table_name}' \
                f' where problem_id=:problem_id'
            response = self.execute_statement(sql, sql_parameters)
            returned_records = response['records']
            if len(returned_records) > 0:
                return returned_records[0][0]['longValue'], returned_records[0][1]['stringValue'], \
                    returned_records[0][2]['stringValue'], returned_records[0][3]['stringValue'], \
                    returned_records[0][4]['longValue']
            else:
                return 0,"","","",0
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def create_problem(self, user_id, event_id, crew_type, strip, problem_type):
        DataAccessLayer._xray_start('create_problem')
        try:
            DataAccessLayer._xray_add_metadata('event', event_id)
            DataAccessLayer._xray_add_metadata('crew', crew_type)
            DataAccessLayer._xray_add_metadata('strip', strip)
            DataAccessLayer._xray_add_metadata('problem', problem_type)
            DataAccessLayer._xray_add_metadata('user', user_id)
            sql_parameters = [
                {'name':'event', 'value':{'longValue': event_id}},
                {'name':'crew', 'value':{'stringValue': crew_type}},
                {'name':'strip', 'value':{'stringValue': strip}},
                {'name':'problem', 'value':{'stringValue': problem_type}},
                {'name':'user', 'value':{'longValue': user_id}},
            ]
            sql = f'insert into {problems_table_name}' \
                f' (event_id, crew_type, strip, problem_type, reporter_id, reported_time_utc)' \
                f' values (:event, :crew, :strip, :problem, :user, now())'
            response = self.execute_statement(sql, sql_parameters)
            return response['numberOfRecordsUpdated'] == 1
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def resolve_problem(self, user_id, problem_id, resolution_code):
        DataAccessLayer._xray_start('resolve_problem')
        try:
            DataAccessLayer._xray_add_metadata('problem', problem_id)
            DataAccessLayer._xray_add_metadata('resolution_code', resolution_code)
            DataAccessLayer._xray_add_metadata('user', user_id)
            sql_parameters = [
                {'name':'problem', 'value':{'longValue': problem_id}},
                {'name':'resolution', 'value':{'longValue': resolution_code}},
                {'name':'user', 'value':{'longValue': user_id}},
                ]
            sql = f'UPDATE {problems_table_name} ' \
                f' SET resolver_id = :user, resolver_time_utc = now(), resolution_code = :resolution' \
                f' WHERE problem_id = :problem'
            response = self.execute_statement(sql, sql_parameters)
            return response['numberOfRecordsUpdated']==1
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def update_problem(self, user_id, problem_id, crew_type, strip, problem_type):
        DataAccessLayer._xray_start('update_problem')
        try:
            DataAccessLayer._xray_add_metadata('problem', problem_id)
            DataAccessLayer._xray_add_metadata('strip', strip)
            DataAccessLayer._xray_add_metadata('problem_type', problem_type)
            DataAccessLayer._xray_add_metadata('crew_type', problem_type)
            DataAccessLayer._xray_add_metadata('user', user_id)
            sql_parameters = [
                {'name':'problem', 'value':{'longValue': problem_id}},
                {'name':'strip', 'value':{'stringValue': strip}},
                {'name':'problem_type', 'value':{'stringValue': problem_type}},
                {'name':'crew', 'value':{'stringValue': crew_type}},
                {'name':'user', 'value':{'longValue': user_id}},
            ]
            sql = f'UPDATE {problems_table_name} ' \
                f' SET strip = :strip, problem_type = :problem_type, updater_id = :user, update_time_utc = now()' \
                f' WHERE problem_id = :problem' \
                f' AND crew_type = :crew'
            response = self.execute_statement(sql, sql_parameters)
            return response['numberOfRecordsUpdated']==1
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def message(self, user_id, event_id, crew_type, problem_id, message_text):
        DataAccessLayer._xray_start('message')
        try:
            #First we create the new message
            #Then we create receipts for the crew that gets the message
            #Then we have to look at the sender and reporter
            #if either is using the app and not in the crew, we create a receipt
            #if either is on SMS, we send the message via TWILIO
            #note that (at least for now) if both are on SMS, then sender=reporter
            DataAccessLayer._xray_add_metadata('event', event_id)
            DataAccessLayer._xray_add_metadata('crew', crew_type)
            DataAccessLayer._xray_add_metadata('problem', problem_id)
            DataAccessLayer._xray_add_metadata('text', message_text)
            DataAccessLayer._xray_add_metadata('user', user_id)
            sql_parameters = [
                {'name':'event', 'value':{'longValue': event_id}},
                {'name':'crew', 'value':{'stringValue': crew_type}},
                {'name':'problem', 'value':{'longValue': problem_id}},
                {'name':'text', 'value':{'stringValue': message_text}},
                {'name':'user', 'value':{'longValue': user_id}},
            ]
            sql = f'insert into {messages_table_name}' \
                f' (event_id, crew_type, problem_id, message_text, sender_id, sent_time_utc)' \
                f' values (:event, :crew, :problem, :text, :user, now())'
            response = self.execute_statement(sql, sql_parameters)
            if response['numberOfRecordsUpdated']!=1:
                logger.info('failed to insert problem')
                return True
            sql = f'SELECT message_id from {messages_table_name} WHERE' \
                f' event_id=:event AND crew_type=:crew AND problem_id=:problem AND message_text=:text AND sender_id=:user'
            response = self.execute_statement(sql, sql_parameters)
            records = response['records']
            if len(records) < 1:
                logger.info('failed to retrieve message id')
                return False
            message_id = records[len(records)-1][0]['longValue']
            logger.info(f'message {message_id}')
                #create receipt records for all crew members
            sql_parameters = [
                {'name':'problem', 'value':{'longValue': problem_id}},
            ]
            sql = f'select strip, problem_type, reporter_id from {problems_table_name} ' \
                f'where problem_id=:problem'
            response = self.execute_statement(sql, sql_parameters)
            records = response['records']
            if len(records) != 1:
                logger.info(f'could not get reporter for problem {problem_id}')
                return False
            strip = records[0][0]['stringValue']
            ptype = records[0][1]['stringValue']
            prbtype = ptype[0:2]
            print(f'ptype={prbtype}, strip={strip}')
            reporter_id = records[0][2]['longValue']
            fcm_data = {"notification": { "title": strip, "body": message_text}, "to": "/topics/"+str(event_id)+crew_type,
                "data": {'message_id': message_id}}
            print(fcm_data)
            fcm_data_json = json.dumps(fcm_data)
            print(fcm_data_json)
            key = f'Key={FCM_KEY}'
            fcm_headers = {'Content-type': 'application/json', 'Authorization': key}
            print(fcm_headers)
            url = 'https://fcm.googleapis.com/fcm/send'
            response = requests.post(url, data=fcm_data_json, headers=fcm_headers)
            print(f'back from request, response={response}')
            if response.status_code != 200:
                logger.info(f'could not send notification to FCM, response was {response}')
                return false
            jsonResponse = json.loads(response.content)
            print(jsonResponse)

            sql_parameters = [
                {'name':'event', 'value':{'longValue': event_id}},
                {'name':'crew', 'value':{'stringValue': crew_type}},
            ]
            sql = f'select user_id, sms from {crews_table_name} '\
                f'where event_id=:event AND crew_type=:crew'
            response = self.execute_statement(sql, sql_parameters)
            records = response['records']
            num_records = len(records)
            logger.info(f'crew size={num_records}')
            if num_records<1:
                return False
            sql_parameters_sets = []
            sms_crew = []
            reporter_increw = False
            sender_increw = False
            for record in records:
                print(record)
                recipient_id = record[0]['longValue']
                if recipient_id == user_id:
                    sender_increw = True #sender is in the crew
                if recipient_id == reporter_id:
                    reporter_increw = True #problem reporter is in the crew
                sms = record[1]['booleanValue']
                print(f'SMS crewmember {sms}')
                if sms==True:
                    sms_crew.append(recipient_id)
                    print(f'sms_crew={sms_crew}')
                    num_records -= 1
                else:
                    logger.info(f'Adding receipt for {recipient_id}')
                    sql_parameters_sets.append([
                        {'name':'event', 'value':{'longValue': event_id}},
                        {'name':'problem', 'value':{'longValue': problem_id}},
                        {'name':'message', 'value':{'longValue': message_id}},
                        {'name':'recipient', 'value':{'longValue': recipient_id}},
                    ])
            sql = f'insert into {receipts_table_name}' \
                f'(event_id, problem_id, message_id, recipient_id) ' \
                f'values (:event, :problem, :message, :recipient)'
            response = self.batch_execute_statement(sql, sql_parameters_sets, 100)
            num_updated = len(response[0]['updateResults'])
            print(f'num_updated={num_updated}')
            print(f'sender={user_id}, reporter={reporter_id}, {sender_increw}, {reporter_increw}')
            if num_updated != num_records:
                logger.info(f'receipt update failed, got {num_updated} expected {num_records}')
                return False
            #sender could be sms or reporter could be sms but if sender is sms, he has to be the reporter.
            test_id=""
            if reporter_increw:
                if sender_increw:
                    test_id=""#return True  #both reporter and sender are in crew, nothing else to do
                else:
                    test_id = sender_id #repprter is in, sender is not
            else:
                if sender_increw:
                    test_id = reporter_id  #sender is in  reporter is not
                else:
                    if user_id != reporter_id:
                        logger.info(f'neither sender {user_id} nor reporter {reporter_id} is in crew but reporter <> sender')
                        return False
                    if user_id == reporter_id:
                        test_id="" #sender = reporter and sms, so no sms needed
                    else: test_id=reporter_id #they are the same, doesn't matter which
            print(f'test_id={test_id}')
            if test_id != "":
                sql_parameters = [
                    {'name':'user', 'value':{'longValue': test_id}},
                    ]
                sql = f'select sub from {users_table_name} '\
                    f'where user_id=:user'
                response = self.execute_statement(sql, sql_parameters)
                records = response['records']
                if len(records)!=1:
                    logger.info(f'could not get mobile for user {test_id}')
                    return False
                print(f'records={records}')
                subDict = records[0][0]
                print(subDict)
                if 'stringValue' in subDict: #user is on app, create receipt
                    logger.info(f'Adding receipt for {test_id}')
                    sql_parameters = [
                        {'name':'event', 'value':{'longValue': event_id}},
                        {'name':'problem', 'value':{'longValue': problem_id}},
                        {'name':'message', 'value':{'longValue': message_id}},
                        {'name':'recipient', 'value':{'longValue': test_id}},
                        ]
                    sql = f'insert into {receipts_table_name}' \
                        f'(event_id, problem_id, message_id, recipient_id) ' \
                        f'values (:event, :problem, :message, :recipient)'
                    response = self.execute_statement(sql, sql_parameters)
                    if response['numberOfRecordsUpdated']!=1:
                        logger.info(f'Failed to insert receipt for user {test_id}')
                        return False
                else:
                    sms_crew.append(test_id)

            if len(sms_crew)==0: return True # no SMS
            sql_parameters = [
                {'name':'event', 'value':{'longValue': event_id}},
                {'name':'crew', 'value':{'stringValue': 'ARM'}},
            ]
            sql = f'select arm_tn from {events_table_name} '\
                f'where event_id=:event'
            response = self.execute_statement(sql, sql_parameters)
            records = response['records']
            if len(records) != 1:
                logger.info(f'could not get twilio tn for event {event_id}')
                return False
            from_tn = records[0][0]['stringValue']
            logger.info(f'from_tn {from_tn}')
            TWILIO_SMS_URL = "https://api.twilio.com/2010-04-01/Accounts/{}/Messages.json"
            populated_url = TWILIO_SMS_URL.format(TWILIO_ACCOUNT_SID)
            print(populated_url)
            for send_id in sms_crew:
                sql_parameters = [
                    {'name':'user', 'value':{'longValue': send_id}},
                    ]
                sql = f'select mobile from {users_table_name} '\
                    f'where user_id=:user'
                response = self.execute_statement(sql, sql_parameters)
                records = response['records']
                if len(records)!=1:
                    logger.info(f'could not get mobile for user {send_id}')
                    return False
                print(f'records={records}')
                toDict = records[0][0]
                print(f'to response={toDict}')
                if 'stringValue' not in toDict:
                    return False
                to_tn = toDict['stringValue']
                logger.info(f'to_tn {to_tn}')

                post_params = {"To": to_tn, "From": from_tn, "Body": message_text}
                print(post_params)
                # encode the parameters for Python's urllib
                data = parse.urlencode(post_params).encode()
                req = request.Request(populated_url)

                # add authentication header to request based on Account SID + Auth Token
                authentication = "{}:{}".format(TWILIO_ACCOUNT_SID, TWILIO_AUTH)
                base64string = base64.b64encode(authentication.encode('utf-8'))
                print("Basic %s" % base64string.decode('ascii'))
                req.add_header("Authorization", "Basic %s" % base64string.decode('ascii'))
                with request.urlopen(req, data) as f:
                    logger.info("Twilio returned {}".format(str(f.read().decode('utf-8'))))

            return True
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def poll(self, user_id, event_id, crew_type):
        DataAccessLayer._xray_start('poll')
        try:
            sql_parameters = [
                {'name':'user', 'value':{'longValue': user_id}},
                {'name':'event', 'value':{'longValue': event_id}},
                {'name':'crew', 'value':{'stringValue': crew_type}},
            ]
            sql = f'select {problems_table_name}.problem_id, {problems_table_name}.strip, {problems_table_name}.problem_type, '\
                f' {users_table_name}.user_name' \
                f' from {problems_table_name} inner join {users_table_name} ON' \
                f' {problems_table_name}.reporter_id = {users_table_name}.user_id' \
                f' where {problems_table_name}.event_id = :event' \
                f' and {problems_table_name}.crew_type = :crew' \
                f' and {problems_table_name}.resolution_code is null'
            response = self.execute_statement(sql, sql_parameters)
            problem_results = [
                {
                    'problem_id': record[0]['longValue'],
                    'strip': record[1]['stringValue'],
                    'problem_type': record[2]['stringValue'],
                    'reporter': record[3]['stringValue']
                }
                for record in response['records']
            ]
            sql = f'select {messages_table_name}.message_id, {messages_table_name}.problem_id,' \
                f' {messages_table_name}.message_text' \
                f' from {messages_table_name}' \
                f' inner join {receipts_table_name}' \
                f' on {messages_table_name}.message_id = {receipts_table_name}.message_id' \
                f' where {messages_table_name}.event_id = :event' \
                f' and {messages_table_name}.crew_type = :crew' \
                f' and {receipts_table_name}.recipient_id = :user' \
                f' and {receipts_table_name}.receipt_time_utc is null'
            response = self.execute_statement(sql, sql_parameters)
            message_results = [
                {
                    'message_id': record[0]['longValue'],
                    'problem_id': record[1]['longValue'],
                    'message_text': record[2]['stringValue']
                }
                for record in response['records']
            ]
            return problem_results, message_results
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def receipt(self, user_id, message_id):
        DataAccessLayer._xray_start('receipt')
        try:
            DataAccessLayer._xray_add_metadata('message_id', message_id)
            DataAccessLayer._xray_add_metadata('user', user_id)
            sql_parameters = [
                {'name':'message', 'value':{'longValue': message_id}},
                {'name':'user', 'value':{'longValue': user_id}},
                ]
            sql = f'UPDATE {receipts_table_name} ' \
                f' SET receipt_time_utc = now() ' \
                f' WHERE message_id = :message AND recipient_id=:user'
            response = self.execute_statement(sql, sql_parameters)
            return response['numberOfRecordsUpdated']>=1
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def hello(self, event_id, user_id):
        DataAccessLayer._xray_start('hello')
        try:
            DataAccessLayer._xray_add_metadata('event', crew_type)
            DataAccessLayer._xray_add_metadata('user', user_id)
            sql_parameters = [
                {'name':'event', 'value':{'longValue': event_id}},
                {'name':'user', 'value':{'longValue': user_id}},
                ]
            sql = f'SELECT crew_id, crew_type FROM {crews_table_name} ' \
                f' WHERE event_id = :event AND user_id = :user'
            response = self.execute_statement(sql, sql_parameters)
            results = [
                {
                    'crew_id': record[0]['longValue'],
                    'crew_type': record[1]['stringValue'],
                }
                for record in response['records']
            ]
            return results
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def tourney(self):
        DataAccessLayer._xray_start('tourney')
        try:
            sql = f'SElECT * FROM {events_table_name} ' \
                    f' WHERE (start_date_utc<now() AND end_date_utc>now())'
            response = self.execute_statement(sql)
            results = [
                {
                    'event_id': record[0]['longValue'],
                    'event_name': record[1]['stringValue'],
                    'event_type': record[2]['stringValue'],
                    'start_date_utc': record[3]['stringValue'],
                    'end_date_utc': record[4]['stringValue'],
                    'state': record[5]['longValue']
                }
                for record in response['records']
            ]
            return results
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def old_events(self):
        DataAccessLayer._xray_start('old_events')
        try:
            sql = f'SElECT event_id, state FROM {events_table_name} ' \
                    f' WHERE end_date_utc<now() AND state != 2'
            response = self.execute_statement(sql)
            print(response['records'])
            results = [
                {
                    'event_id': record[0]['longValue'],
                    'state': record[1]['longValue']
                }
                for record in response['records']
            ]
            return results
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def add_crew(self, event_id, crew_type, user_id):
        DataAccessLayer._xray_start('add_crew')
        try:
            DataAccessLayer._xray_add_metadata('event', event_id)
            DataAccessLayer._xray_add_metadata('crew', crew_type)
            DataAccessLayer._xray_add_metadata('user', user_id)
            sql_parameters = [
                {'name':'event', 'value':{'longValue': event_id}},
                {'name':'user', 'value':{'longValue': user_id}},
            ]
            sql = f'select crew_id' \
                f' from {crews_table_name}' \
                f' where user_id=:user' \
                f' and event_id=:event'
            response = self.execute_statement(sql, sql_parameters)
            returned_records = response['records']
            if len(returned_records) >= 1:
                return 1
            sql_parameters = [
                {'name':'event', 'value':{'longValue': event_id}},
                {'name':'crew', 'value':{'stringValue': crew_type}},
                {'name':'user', 'value':{'longValue': user_id}},
                ]
            sql = f'INSERT INTO {crews_table_name} ' \
                f' (event_id, crew_type,user_id, sms) ' \
                f' VALUES (:event, :crew, :user, false)'
            response = self.execute_statement(sql, sql_parameters)
            return response['numberOfRecordsUpdated']
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def change_state(self, event_id, new_state):
        DataAccessLayer._xray_add_metadata('event', event_id)
        DataAccessLayer._xray_add_metadata('state', new_state)
        try:
            sql_parameters = [
                {'name':'event', 'value':{'longValue': event_id}},
                {'name':'state', 'value':{'longValue': new_state}},
            ]
            sql = f'UPDATE {events_table_name} ' \
                f' SET state = :state' \
                f' WHERE event_id = :event'
            response = self.execute_statement(sql, sql_parameters)
            return response['numberOfRecordsUpdated']
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()


    def cleanup(self, event_id):
        DataAccessLayer._xray_add_metadata('event', event_id)
        event_sql_parameters = [
            {'name':'event', 'value':{'longValue': event_id}}
        ]
        try:
            sql = f'SELECT receipt_id from {receipts_table_name} ' \
                f' WHERE event_id = :event' \
                f' AND receipt_time_utc IS NULL'
            response = self.execute_statement(sql, event_sql_parameters)
            returned_records = response['records']
            for record in returned_records:
                receipt_id = record[0]['longValue']
                sql_parameters = [
                    {'name':'receipt', 'value':{'longValue': receipt_id}}
                ]
                sql = f'UPDATE {receipts_table_name} ' \
                    f' SET receipt_time_utc = now()' \
                    f' WHERE receipt_id = :receipt'
                receipt_response = self.execute_statement(sql, sql_parameters)
            sql = f'SELECT message_id from {messages_table_name} ' \
                f' WHERE event_id = :event' \
                f' AND finished_time_utc IS NULL'
            response = self.execute_statement(sql, event_sql_parameters)
            returned_records = response['records']
            for record in returned_records:
                message_id = record[0]['longValue']

                sql_parameters = [
                    {'name':'message', 'value':{'longValue': message_id}}
                ]
                sql = f'UPDATE {messages_table_name} ' \
                    f' SET finished_time_utc = now()' \
                    f' WHERE message_id = :message'
                message_response = self.execute_statement(sql, sql_parameters)
            sql = f'SELECT problem_id from {problems_table_name} ' \
                f' WHERE event_id = :event' \
                f' AND resolver_id IS NULL'
            response = self.execute_statement(sql, event_sql_parameters)
            returned_records = response['records']
            for record in returned_records:
                problem_id = record[0]['longValue']

                sql_parameters = [
                    {'name':'problem', 'value':{'longValue': problem_id}}
                ]
                sql = f'UPDATE {problems_table_name} ' \
                    f' SET resolver_id = 1001, resolver_time_utc = now(), resolution_code=77' \
                    f' WHERE problem_id = :problem'
                problem_response = self.execute_statement(sql, sql_parameters)
            return 1
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()


    def sms_incoming(self, to_tn, from_tn, msg):
        DataAccessLayer._xray_start('sms incoming')
        DataAccessLayer._xray_add_metadata('totn', to_tn)
        DataAccessLayer._xray_add_metadata('fromtn', from_tn)
        try:
            role = 'REF'
            sql_parameters = [
                {'name':'tn', 'value':{'stringValue': from_tn}},
                {'name':'role', 'value':{'stringValue': role}},
            ]
            sql = f'SELECT user_id, user_name FROM {users_table_name} ' \
                f' WHERE mobile = :tn'
            response = self.execute_statement(sql,sql_parameters) #lookup ref by tn
            returned_records = response['records']
            if len(returned_records) == 0: #new ref
                sql = f'INSERT INTO {users_table_name} (user_name, full_name, allowed_roles, mobile) ' \
                    f' VALUES (:tn, :tn, :role, :tn)'
                insert_response = self.execute_statement(sql,sql_parameters)
                if insert_response['numberOfRecordsUpdated']==1:
                    sql = f'SELECT user_id from {users_table_name} where user_name=:tn'
                    last_response = self.execute_statement(sql,sql_parameters)
                    records = last_response['records']
                    user_id = records[0][0]['longValue']
                    user_name = from_tn
                else:
                    return(0)
            else: #existing user
                user_id=response['records'][0][0]['longValue']
                user_name = response['records'][0][1]['stringValue']
            logger.info(user_id)
            # should checl/insert into crew table
            crew_type = 'ARM'
            sql_parameters = [
                {'name':'tn', 'value':{'stringValue': to_tn}},
                {'name':'crew', 'value':{'stringValue': crew_type}},
            ]
            sql = f'SELECT event_id FROM {events_table_name} ' \
                f' WHERE arm_tn=:tn'
            event_response = self.execute_statement(sql,sql_parameters)
            returned_records = event_response['records']
            if len(returned_records)!=1:
                return(1)
            event_id = returned_records[0][0]['longValue']
            logger.info(event_id)
            sql_parameters = [
                {'name':'user_id', 'value':{'longValue': user_id}},
            ]
            sql = f'SELECT problem_id FROM {problems_table_name} ' \
                f' WHERE reporter_id=:user_id AND resolution_code IS NULL'
            prob_response = self.execute_statement(sql,sql_parameters)
            returned_records = prob_response['records']
            newProb=False
            if len(returned_records)==0: #new problem
                newProb = True
                msg_words = msg.split()
                print(msg)
                print(msg_words)
                strip = 'A1'
                problem_type = 'A62' # Other Other
                onceKeywords = {'grounding':'A00', 'separating':'A10', 'straighten':'A11', 'missing':'A20',
                    'batteries':'A21', 'machine':'A30', 'lame':'A40', 'epee':'A41',
                    'clip':'A50', 'bail':'A51', 'phantom':'A60', 'unknown':'A62'}
                print(f'len: {len(msg_words)} max={min(len(msg_words), 4)}')
                otherKeywords = { 'remote':'A22', 'reel':'A52'}
                print(f'len: {len(msg_words)} max={min(len(msg_words), 4)}')
                for tok in msg_words:
                    token = tok.lower()
                    if len(token)==2 and token[0].isalpha() and token[1].isdecimal():
                        strip = token.capitalize()
                        print(f'new strip: {strip}')
                    if token in onceKeywords:
                        problem_type = onceKeywords[token]
                    if problem_type != 'A62' and (token in otherKeywords):
                        problem_type = otherKeywords[token]
                sql_parameters = [
                    {'name':'event', 'value':{'longValue': event_id}},
                    {'name':'crew', 'value':{'stringValue': crew_type}},
                    {'name':'strip', 'value':{'stringValue': strip}},
                    {'name':'problem', 'value':{'stringValue': problem_type}},
                    {'name':'user', 'value':{'longValue': user_id}},
                ]
                sql = f'insert into {problems_table_name}' \
                    f' (event_id, crew_type, strip, problem_type, reporter_id, reported_time_utc)' \
                    f' values (:event, :crew, :strip, :problem, :user, now())'
                prob_response = self.execute_statement(sql, sql_parameters)
                if prob_response['numberOfRecordsUpdated'] != 1:
                    return(3)
                sql = f'SELECT MAX(problem_id) from {problems_table_name};'
                last_response = self.execute_statement(sql)
                records = last_response['records']
                problem_id = records[0][0]['longValue']
            else:
                problem_id = returned_records[0][0]['longValue']
            logger.info(problem_id)
            sql_parameters = [
                {'name':'user', 'value':{'longValue': user_id}},
                {'name':'event', 'value':{'longValue': event_id}},
            ]
            sql = f'SELECT crew_id FROM {crews_table_name} ' \
                f' WHERE user_id=:user and event_id=:event'
            crew_response = self.execute_statement(sql,sql_parameters)
            returned_records = crew_response['records']  #fix here
            if not self.message(user_id, event_id, crew_type, problem_id, user_name+":"+msg):
                return(4)
            else:
                if newProb:
                    return(5)
                else:
                    return(6)

        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()


    def insert_email(self, email, full_name, user_name, role):
        DataAccessLayer._xray_add_metadata('email', email)
        DataAccessLayer._xray_add_metadata('first_name', full_name)
        DataAccessLayer._xray_add_metadata('last_name', user_name)
        DataAccessLayer._xray_add_metadata('role', role)
        try:
            sql_parameters = [
                {'name':'email', 'value':{'stringValue': email.lower()}},
            ]
            sql = f'SELECT user_id, allowed_roles  FROM {users_table_name} ' \
                f' WHERE email = :email'
            response = self.execute_statement(sql, sql_parameters)
            returned_records = response['records']
            if len(returned_records) > 0: #already have a record with that email
                allowed_roles = returned_records[0][1]['stringValue']
                if (role in allowed_roles):
                    return True #record is up to date, nothing else to do
                user_id = returned_records[0][0]['longValue'] #add another role
                allowed_roles=allowed_roles+","+role.upper()
                sql_parameters = [
                    {'name':'user', 'value':{'longValue': user_id}},
                    {'name':'roles', 'value':{'stringValue': allowed_roles}},
                ]
                sql = f'UPDATE {users_table_name} ' \
                    f' SET allowed_roles=:roles ' \
                    f' WHERE user_id=:user '
                response = self.execute_statement(sql, sql_parameters)
                if response['numberOfRecordsUpdated'] != 1:
                    return False
                return True
            sql_parameters = [ #here if no record with that email exists, add a new one
                {'name':'email', 'value':{'stringValue': email.lower()}},
                {'name':'full', 'value':{'stringValue': full_name}},
                {'name':'user', 'value':{'stringValue': user_name}},
                {'name':'role', 'value':{'stringValue': role}},
            ]
            sql=f'INSERT INTO {users_table_name} (full_name, user_name, allowed_roles, email) ' \
                f'VALUES(:full, :user, :role, :email)'
            response = self.execute_statement(sql, sql_parameters)
            if response['numberOfRecordsUpdated'] != 1:
                return False
            return True
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def check_email(self, email):
        DataAccessLayer._xray_add_metadata('email', email)
        try:
            sql_parameters = [
                {'name':'email', 'value':{'stringValue': email.lower()}},
            ]
            sql = f'SELECT user_id, allowed_roles  FROM {users_table_name} ' \
                f' WHERE email = :email'
            response = self.execute_statement(sql, sql_parameters)
            print(response)
            returned_records = response['records']
            if returned_records: #already have a record with that email
                return True
            return False
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()

    def insert_sub(self, email, sub):
        DataAccessLayer._xray_add_metadata('email', email)
        DataAccessLayer._xray_add_metadata('sub', sub)

        try:
            sql_parameters = [
                {'name':'email', 'value':{'stringValue': email.lower()}},
                {'name':'sub', 'value':{'stringValue': sub}},
            ]
            sql = f'UPDATE {users_table_name} ' \
                f' SET sub=:sub ' \
                f' WHERE email=:email '
            response = self.execute_statement(sql, sql_parameters)
            if response['numberOfRecordsUpdated'] != 1:
                return False
            return True
        except DataAccessLayerException as de:
            raise de
        except Exception as e:
            raise DataAccessLayerException(e) from e
        finally:
            DataAccessLayer._xray_stop()
