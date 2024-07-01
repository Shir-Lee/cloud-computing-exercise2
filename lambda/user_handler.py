import json
import uuid
from datetime import datetime
import os
import redis
import pymysql

users_table = 'users_table'
blocks_table = 'blocks_table'
user_messages_table = 'user_messages_table'
cache_length = 20


def register_lambda(event, context):
    global result

    try:
        # parse input
        user_name = event['queryStringParameters']['user_name']
        # user_number = event['queryStringParameters']['user_number']
        user_id = str(uuid.uuid4())

        # update db
        connection = pymysql.connect(
            host=os.environ['DB_HOST'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASS']
        )
        with connection:
            with connection.cursor() as cursor:
                # create table
                cursor.execute(f'CREATE DATABASE IF NOT EXISTS mydatabase;')
                cursor.execute("USE mydatabase")
                cursor.execute(
                    f'CREATE TABLE IF NOT EXISTS {users_table} (user_id VARCHAR(255) PRIMARY KEY, user_name VARCHAR(255));')
                # record in table
                cursor.execute(f"INSERT INTO {users_table} (user_id, user_name) VALUES ('{user_id}', '{user_name}');")
            connection.commit()

        # output
        result = {
            'statusCode': 200,
            'body': json.dumps(f'success in registering! user id: {user_id}')
        }

        return result

    except Exception as e:
        result = {
            'statusCode': 500,
            'body': json.dumps(f"error in registering: {e}")
        }
        return result


def block_lambda(event, context):
    global result

    try:
        # parse input
        blocking_user_id = event['queryStringParameters']['blocking_user_id']
        blocked_user_id = event['queryStringParameters']['blocked_user_id']
        to_block = bool(int(event['queryStringParameters']['to_block']))
        blocking_blocked_pair = "'" + blocking_user_id + ',' + blocked_user_id + "'"

        # update db
        connection = pymysql.connect(
            host=os.environ['DB_HOST'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASS']
        )
        with connection:
            with connection.cursor() as cursor:
                # create table
                cursor.execute(f'CREATE DATABASE IF NOT EXISTS mydatabase;')
                cursor.execute("USE mydatabase")
                cursor.execute(
                    f'CREATE TABLE IF NOT EXISTS {blocks_table} (blocking_blocked_pair VARCHAR(255) PRIMARY KEY);')
                # record in table
                if to_block:
                    # in case of blocking - add it to the table
                    cursor.execute(
                        f"INSERT INTO {blocks_table} (blocking_blocked_pair) VALUES ({blocking_blocked_pair});")
                    action = 'user has been blocked'
                else:
                    # in case of unblocking - remove it from the table
                    cursor.execute(f"DELETE FROM {blocks_table} WHERE blocking_blocked_pair={blocking_blocked_pair};")
                    action = 'user has been unblocked'
            connection.commit()

        # output
        result = {
            'statusCode': 200,
            'body': json.dumps(f'success in (un)blocking: {action}')
        }

        return result

    except Exception as e:
        result = {
            'statusCode': 500,
            'body': json.dumps(f"error in (un)blocking: {e}")
        }
        return result


def send_lambda(event, context):
    global result

    try:
        # parse input
        sending_user_id = event['queryStringParameters']['sending_user_id']
        receiving_user_id = event['queryStringParameters']['receiving_user_id']
        message_text = event['queryStringParameters']['message_text']

        # update db
        connection = pymysql.connect(
            host=os.environ['DB_HOST'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASS']
        )
        with connection:
            with connection.cursor() as cursor:
                # create table
                cursor.execute(f'CREATE DATABASE IF NOT EXISTS mydatabase;')
                cursor.execute("USE mydatabase")
                cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {user_messages_table} (
                message_id VARCHAR(255) PRIMARY KEY,
                sending_user_id VARCHAR(255),
                receiving_user_id VARCHAR(255),
                message_text VARCHAR(255),
                timestamp TIMESTAMP
                );
                """)

                # check blocking
                blocking_blocked_pair = "'" + receiving_user_id + ',' + sending_user_id + "'"
                cursor.execute(f"SELECT * FROM {blocks_table} WHERE blocking_blocked_pair={blocking_blocked_pair};")
                records = cursor.fetchall()
                if records:
                    result = {
                        'statusCode': 400,
                        'body': json.dumps('receiver has blocked the sender')
                    }
                    return result

                # message details
                message_id = str(uuid.uuid4())
                message_timestamp = datetime.now()

                # record
                cursor.execute(f"""
                INSERT INTO {user_messages_table} 
                (message_id, sending_user_id, receiving_user_id, message_text, timestamp) VALUES 
                ('{message_id}', '{sending_user_id}', '{receiving_user_id}', 
                '{message_text}', '{str(message_timestamp)}');
                """)

            connection.commit()

        # send to cache
        redis_host = os.environ['REDIS_HOST']
        cache_client = redis.Redis(host=redis_host, port=6379, db=0)
        is_group = 0
        value = f'{str(message_timestamp)}:: {is_group} {sending_user_id}:: {message_text}'
        # cache_client.set(receiving_user_id, value)
        # cache_client.delete(receiving_user_id)
        # push the new message
        cache_client.lpush(receiving_user_id, value)
        # remove the oldest message
        if cache_client.llen(receiving_user_id) > cache_length:
            cache_client.rpop(receiving_user_id)

        # output
        result = {
            'statusCode': 200,
            'body': json.dumps('success in sending')
        }

        return result

    except Exception as e:
        result = {
            'statusCode': 500,
            'body': json.dumps(f"error in sending: {e}")
        }
        return result
